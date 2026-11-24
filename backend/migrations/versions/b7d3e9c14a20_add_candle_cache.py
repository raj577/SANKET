"""add daily candle cache for performance analysis

Revision ID: b7d3e9c14a20
Revises: c4a91d2f7b30
Create Date: 2026-11-23 10:00:00.000000

Adds two independent tables:

* ``instrument_candles`` caches completed daily OHLCV per provider symbol so the
  day-wise performance analysis never needs a live FYERS call.
* ``candle_backfill_runs`` records the progress of the refresh job that fills
  the cache.

No existing table is altered, so the OI scanner, its candidates and the pattern
scanner are unaffected.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d3e9c14a20"
down_revision: Union[str, None] = "c4a91d2f7b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instrument_candles",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instrument_candles")),
        sa.UniqueConstraint(
            "symbol", "trade_date", name="uq_instrument_candles_symbol_date"
        ),
    )
    op.create_index(
        "ix_instrument_candles_symbol", "instrument_candles", ["symbol"], unique=False
    )
    op.create_index(
        "ix_instrument_candles_trade_date",
        "instrument_candles",
        ["trade_date"],
        unique=False,
    )

    op.create_table(
        "candle_backfill_runs",
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("range_from", sa.Date(), nullable=False),
        sa.Column("range_to", sa.Date(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_symbols", sa.Integer(), nullable=False),
        sa.Column("processed_symbols", sa.Integer(), nullable=False),
        sa.Column("failed_symbols", sa.Integer(), nullable=False),
        sa.Column("candles_written", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "progress",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','PARTIAL','FAILED')",
            name=op.f("ck_candle_backfill_runs_backfill_status_allowed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candle_backfill_runs")),
    )
    op.create_index(
        "ix_candle_backfill_runs_started_at",
        "candle_backfill_runs",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        "ix_candle_backfill_runs_status", "candle_backfill_runs", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_candle_backfill_runs_status", table_name="candle_backfill_runs")
    op.drop_index("ix_candle_backfill_runs_started_at", table_name="candle_backfill_runs")
    op.drop_table("candle_backfill_runs")

    op.drop_index("ix_instrument_candles_trade_date", table_name="instrument_candles")
    op.drop_index("ix_instrument_candles_symbol", table_name="instrument_candles")
    op.drop_table("instrument_candles")
