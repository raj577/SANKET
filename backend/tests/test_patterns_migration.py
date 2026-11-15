"""Alembic migration for the AVWAP pattern scanner.

Runs the real migration chain against a throwaway SQLite file so the upgrade is
exercised exactly as it would be on a deployed database: an existing OI scan row
must survive and receive ``scan_type = 'OI'``.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "9f3c1a7b2d10"

pytestmark = pytest.mark.skipif(
    not (BACKEND_ROOT / "alembic.ini").is_file(),
    reason="alembic.ini is required for the migration test",
)


def _run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def migrated_db(tmp_path: Path):
    db_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{db_path.as_posix()}"

    upgrade = _run_alembic(database_url, "upgrade", PREVIOUS_REVISION)
    assert upgrade.returncode == 0, upgrade.stderr

    # Simulate an existing OI scan recorded before the pattern feature existed.
    old_scan_id = uuid.uuid4().hex
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO scan_runs (
                id, started_at, status, total_symbols, successful_symbols,
                failed_symbols, long_candidates_count, short_candidates_count,
                candidates_processed, trigger, updated_at, created_at
            ) VALUES (?, CURRENT_TIMESTAMP, 'COMPLETED', 10, 10, 0, 3, 2, 1,
                      'collector', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (old_scan_id,),
        )

    head = _run_alembic(database_url, "upgrade", "head")
    assert head.returncode == 0, head.stderr
    yield db_path, old_scan_id, database_url


def _columns(db_path: Path, table: str) -> dict[str, tuple]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1]: row for row in rows}


def test_existing_oi_scan_gets_default_scan_type(migrated_db):
    db_path, old_scan_id, _ = migrated_db
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT scan_type, timeframe, status FROM scan_runs WHERE id = ?",
            (old_scan_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == "OI"
    assert row[1] is None
    assert row[2] == "COMPLETED"


def test_scan_runs_gains_scan_type_and_timeframe_columns(migrated_db):
    db_path, _, _ = migrated_db
    columns = _columns(db_path, "scan_runs")
    assert "scan_type" in columns
    assert columns["scan_type"][3] == 1  # NOT NULL
    assert columns["scan_type"][4] == "'OI'"  # server default (quoted literal)
    assert "timeframe" in columns
    assert columns["timeframe"][3] == 0  # nullable


def test_pattern_candidates_table_is_created(migrated_db):
    db_path, old_scan_id, _ = migrated_db
    columns = _columns(db_path, "pattern_candidates")
    assert {
        "id",
        "scan_id",
        "symbol",
        "underlying",
        "expiry",
        "timeframe",
        "pattern_type",
        "candle_count",
        "last_price",
        "avwap",
        "distance_pct",
        "avg_body_ratio",
        "max_body_ratio",
        "window_range_pct",
        "touched",
        "atr",
        "anchor_at",
        "pattern_start",
        "pattern_end",
        "status",
        "reason",
        "detector_metadata",
        "created_at",
    } <= set(columns)

    # The new table accepts a pattern candidate linked to the migrated scan.
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO pattern_candidates (
                id, scan_id, symbol, underlying, expiry, timeframe,
                pattern_type, candle_count, last_price, avwap, distance_pct,
                avg_body_ratio, max_body_ratio, window_range_pct, touched, atr,
                anchor_at, pattern_start, pattern_end, status, reason,
                detector_metadata, created_at
            ) VALUES (?, ?, 'NSE:NIFTY26NOVFUT', 'NIFTY', '2026-11-26', '60',
                      'AVWAP TOUCH', 1, 100.1, 100.0, 0.1, 0.2, 0.25, 0.004,
                      1, 1.6, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP, 'PENDING', 'AVWAP TOUCH · 1 candle(s)',
                      '{"pattern_type": "AVWAP TOUCH"}', CURRENT_TIMESTAMP)
            """,
            (uuid.uuid4().hex, old_scan_id),
        )
        stored = connection.execute(
            "SELECT pattern_type, status FROM pattern_candidates WHERE scan_id = ?",
            (old_scan_id,),
        ).fetchone()
    assert stored == ("AVWAP TOUCH", "PENDING")


def test_oi_tables_are_untouched(migrated_db):
    db_path, _, _ = migrated_db
    candidate_columns = _columns(db_path, "scan_candidates")
    assert "direction" in candidate_columns
    assert "pattern_type" not in candidate_columns
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"scan_runs", "scan_candidates", "published_signals"} <= tables


def test_downgrade_removes_pattern_schema_only(migrated_db):
    db_path, old_scan_id, database_url = migrated_db

    downgrade = _run_alembic(database_url, "downgrade", PREVIOUS_REVISION)
    assert downgrade.returncode == 0, downgrade.stderr

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(scan_runs)").fetchall()
        }
        scan = connection.execute(
            "SELECT status FROM scan_runs WHERE id = ?", (old_scan_id,)
        ).fetchone()

    assert "pattern_candidates" not in tables
    assert "scan_type" not in columns
    assert "timeframe" not in columns
    assert scan == ("COMPLETED",)
