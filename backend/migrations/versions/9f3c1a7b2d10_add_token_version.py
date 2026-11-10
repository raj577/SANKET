"""add user token_version for session revocation

Revision ID: 9f3c1a7b2d10
Revises: 77650cc344fc
Create Date: 2026-11-09
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9f3c1a7b2d10"
down_revision: Union[str, None] = "77650cc344fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
