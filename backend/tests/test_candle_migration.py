"""Alembic migration for the daily candle cache.

Runs the real chain on a throwaway SQLite file: existing OI scans and
candidates must survive, the two new tables must appear, and the downgrade must
remove only the new tables.
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
PREVIOUS_REVISION = "c4a91d2f7b30"

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
    db_path = tmp_path / "candles.db"
    database_url = f"sqlite:///{db_path.as_posix()}"

    upgrade = _run_alembic(database_url, "upgrade", PREVIOUS_REVISION)
    assert upgrade.returncode == 0, upgrade.stderr

    scan_id = uuid.uuid4().hex
    candidate_id = uuid.uuid4().hex
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO scan_runs (
                id, started_at, status, scan_type, total_symbols,
                successful_symbols, failed_symbols, long_candidates_count,
                short_candidates_count, candidates_processed, trigger,
                updated_at, created_at
            ) VALUES (?, CURRENT_TIMESTAMP, 'COMPLETED', 'OI', 1, 1, 0, 1, 0,
                      1, 'oi', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (scan_id,),
        )
        connection.execute(
            """
            INSERT INTO scan_candidates (
                id, scan_id, symbol, direction, scan_ltp, score, grade, reason,
                confirmation_count, scanned_at, status, created_at
            ) VALUES (?, ?, 'INFY', 'LONG', 100, 10, 'A', '', 1,
                      CURRENT_TIMESTAMP, 'PENDING', CURRENT_TIMESTAMP)
            """,
            (candidate_id, scan_id),
        )

    head = _run_alembic(database_url, "upgrade", "head")
    assert head.returncode == 0, head.stderr
    yield db_path, database_url, scan_id, candidate_id


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }


def _columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_candle_tables_are_created(migrated_db):
    db_path, _, _, _ = migrated_db
    tables = _tables(db_path)
    assert {"instrument_candles", "candle_backfill_runs"} <= tables
    assert {
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "fetched_at",
    } <= _columns(db_path, "instrument_candles")
    assert {
        "status",
        "range_from",
        "range_to",
        "total_symbols",
        "processed_symbols",
        "failed_symbols",
        "candles_written",
        "progress",
    } <= _columns(db_path, "candle_backfill_runs")


def test_oi_data_survives_the_upgrade(migrated_db):
    db_path, _, scan_id, candidate_id = migrated_db
    with sqlite3.connect(db_path) as connection:
        scan = connection.execute(
            "SELECT scan_type, status FROM scan_runs WHERE id = ?", (scan_id,)
        ).fetchone()
        candidate = connection.execute(
            "SELECT symbol, direction, scan_ltp FROM scan_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    assert scan == ("OI", "COMPLETED")
    assert candidate == ("INFY", "LONG", 100)


def test_candles_can_be_stored_without_touching_scans(migrated_db):
    db_path, _, _, _ = migrated_db
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO instrument_candles (
                symbol, trade_date, open, high, low, close, volume, source,
                fetched_at
            ) VALUES ('NSE:INFY-EQ', '2026-11-10', 100, 101, 99, 100.5, 1000,
                      'FYERS', CURRENT_TIMESTAMP)
            """
        )
        row = connection.execute(
            "SELECT close FROM instrument_candles WHERE symbol = 'NSE:INFY-EQ'"
        ).fetchone()
        scans = connection.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
    assert row == (100.5,)
    assert scans == 1


def test_downgrade_removes_only_the_candle_tables(migrated_db):
    db_path, database_url, scan_id, candidate_id = migrated_db

    downgrade = _run_alembic(database_url, "downgrade", PREVIOUS_REVISION)
    assert downgrade.returncode == 0, downgrade.stderr

    tables = _tables(db_path)
    assert "instrument_candles" not in tables
    assert "candle_backfill_runs" not in tables
    assert {"scan_runs", "scan_candidates", "pattern_candidates"} <= tables

    with sqlite3.connect(db_path) as connection:
        scan = connection.execute(
            "SELECT status FROM scan_runs WHERE id = ?", (scan_id,)
        ).fetchone()
        candidate = connection.execute(
            "SELECT symbol FROM scan_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    assert scan == ("COMPLETED",)
    assert candidate == ("INFY",)
