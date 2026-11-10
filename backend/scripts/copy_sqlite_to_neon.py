"""One-off copy: local SQLite dev data -> the configured target database.

Reads the target URL from backend/.env (app settings) and the source from
SRC_DATABASE_URL (default: sqlite:///./run-dev.db). Run from backend/:

    ..\\.venv\\Scripts\\python.exe scripts\\copy_sqlite_to_neon.py

It is fail-closed: the target must already have the schema (Alembic) and must
be empty, otherwise it aborts without writing anything.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import URL, create_engine, func, insert, select, text  # noqa: E402

from app import models  # noqa: E402,F401  (register every table)
from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# The only table whose primary key is a database-generated integer; its
# identity sequence must be advanced after explicit-ID inserts.
INTEGER_PK_TABLES = ("signal_price_history",)


def _utc(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _redact(url: str) -> str:
    try:
        return URL.create(**{**make_url(url)._asdict(), "password": "***"}).render_as_string(hide_password=False)
    except Exception:
        return "<unparsed target>"


from sqlalchemy.engine import make_url  # noqa: E402


def main() -> int:
    source_url = os.environ.get("SRC_DATABASE_URL", "sqlite:///./run-dev.db")
    target_url = get_settings().database_url

    if target_url.startswith("sqlite"):
        print("ABORT: target DATABASE_URL is still sqlite; put the Neon URL in backend/.env first")
        return 2

    print("target:", _redact(target_url))
    try:
        target_engine = create_engine(target_url, pool_pre_ping=True)
        with target_engine.connect() as probe:
            probe.execute(text("SELECT 1"))
        print("target reachable: yes")
    except Exception as exc:  # noqa: BLE001
        print("ABORT: cannot reach target:", type(exc).__name__, str(exc)[:300])
        return 2

    tables: dict[str, Any] = {t.name: t for t in Base.metadata.sorted_tables}
    with target_engine.connect() as conn:
        existing = set(
            conn.execute(
                text("select table_name from information_schema.tables where table_schema='public'")
            ).scalars()
        )
        missing = [name for name in tables if name not in existing]
        if missing:
            print("ABORT: run alembic upgrade head first; missing tables:", ", ".join(missing))
            return 2
        occupied = {
            name: conn.execute(select(func.count()).select_from(table)).scalar()
            for name, table in tables.items()
        }
        non_empty = {name: count for name, count in occupied.items() if count}
        if non_empty:
            print("ABORT: target is not empty:", non_empty)
            return 3
    print("target empty: yes")

    source_engine = create_engine(source_url)
    payloads: dict[str, list[dict[str, Any]]] = {}
    with source_engine.connect() as conn:
        for name, table in tables.items():
            rows = [
                {key: _utc(value) for key, value in dict(row).items()}
                for row in conn.execute(select(table)).mappings()
            ]
            payloads[name] = rows
            print(f"source {name}: {len(rows)} rows")

    total = 0
    with target_engine.begin() as conn:
        for name, table in tables.items():
            rows = payloads[name]
            if rows:
                # 500-row chunks; tiny here but harmless at scale.
                for start in range(0, len(rows), 500):
                    conn.execute(insert(table), rows[start : start + 500])
            print(f"copied {name}: {len(rows)}")
            total += len(rows)

        if target_engine.dialect.name == "postgresql":
            for name in INTEGER_PK_TABLES:
                seq = conn.execute(
                    text("select pg_get_serial_sequence(:tn, :cn)"),
                    {"tn": name, "cn": "id"},
                ).scalar()
                if seq:
                    conn.execute(
                        text(
                            f"select setval('{seq}', "
                            f"greatest((select coalesce(max(id), 0) from {name}), 1), true)"
                        )
                    )
                    print(f"sequence advanced for {name}: {seq}")

    print(f"TOTAL rows copied: {total}")
    with target_engine.connect() as conn:
        for name, table in tables.items():
            count = conn.execute(select(func.count()).select_from(table)).scalar()
            print(f"verify {name}: {count}")
            if count != len(payloads[name]):
                print(f"MISMATCH on {name}; investigate before switching traffic")
                return 4

    source_engine.dispose()
    target_engine.dispose()
    print("COPY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
