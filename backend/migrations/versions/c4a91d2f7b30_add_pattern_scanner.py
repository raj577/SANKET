"""add AVWAP pattern scanner

Revision ID: c4a91d2f7b30
Revises: 9f3c1a7b2d10
Create Date: 2026-11-15 19:40:00.000000

Adds the scan-type discriminator to ``scan_runs`` and a dedicated
``pattern_candidates`` table. Existing scan rows receive ``scan_type = 'OI'``
through the column server default, so no data migration is required and the OI
candidate schema is left untouched.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4a91d2f7b30"
down_revision: Union[str, None] = "9f3c1a7b2d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scan_runs",
        sa.Column(
            "scan_type",
            sa.String(length=24),
            nullable=False,
            server_default="OI",
        ),
    )
    op.add_column(
        "scan_runs",
        sa.Column("timeframe", sa.String(length=8), nullable=True),
    )
    op.create_index("ix_scan_runs_scan_type", "scan_runs", ["scan_type"], unique=False)

    op.create_table(
        "pattern_candidates",
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("underlying", sa.String(length=32), nullable=True),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("pattern_type", sa.String(length=32), nullable=False),
        sa.Column("candle_count", sa.Integer(), nullable=False),
        sa.Column("last_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("avwap", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("distance_pct", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("avg_body_ratio", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("max_body_ratio", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("window_range_pct", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("touched", sa.Boolean(), nullable=False),
        sa.Column("atr", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pattern_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pattern_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "detector_metadata",
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
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','PUBLISHED','EXPIRED')",
            name=op.f("ck_pattern_candidates_pattern_candidate_status_allowed"),
        ),
        sa.CheckConstraint(
            "pattern_type IN ("
            "'AVWAP TOUCH','AVWAP HUGGING','AVWAP CONSOLIDATION','AVWAP RECLAIM'"
            ")",
            name=op.f("ck_pattern_candidates_pattern_candidate_type_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scan_runs.id"],
            name=op.f("fk_pattern_candidates_scan_id_scan_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pattern_candidates")),
    )
    op.create_index(
        "ix_pattern_candidates_pattern_type",
        "pattern_candidates",
        ["pattern_type"],
        unique=False,
    )
    op.create_index(
        "ix_pattern_candidates_scan_id",
        "pattern_candidates",
        ["scan_id"],
        unique=False,
    )
    op.create_index(
        "ix_pattern_candidates_status",
        "pattern_candidates",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_pattern_candidates_symbol",
        "pattern_candidates",
        ["symbol"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pattern_candidates_symbol", table_name="pattern_candidates")
    op.drop_index("ix_pattern_candidates_status", table_name="pattern_candidates")
    op.drop_index("ix_pattern_candidates_scan_id", table_name="pattern_candidates")
    op.drop_index("ix_pattern_candidates_pattern_type", table_name="pattern_candidates")
    op.drop_table("pattern_candidates")

    op.drop_index("ix_scan_runs_scan_type", table_name="scan_runs")
    op.drop_column("scan_runs", "timeframe")
    op.drop_column("scan_runs", "scan_type")
