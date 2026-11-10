"""Scan run and filtered candidate models. Never stores raw option-chain data."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import CandidateStatus, ScanStatus


class ScanRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scan_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','PARTIAL','FAILED')",
            name="scan_status_allowed",
        ),
        Index("ix_scan_runs_started_at", "started_at"),
        Index("ix_scan_runs_status", "status"),
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ScanStatus.PENDING.value
    )
    total_symbols: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful_symbols: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_symbols: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    long_candidates_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    short_candidates_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    csv_filename: Mapped[str | None] = mapped_column(String(255))
    csv_storage_path: Mapped[str | None] = mapped_column(String(512))
    csv_size_bytes: Mapped[int | None] = mapped_column(Integer)
    csv_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csv_checksum_sha256: Mapped[str | None] = mapped_column(String(64))

    scanner_version: Mapped[str | None] = mapped_column(String(32))
    scanner_config: Mapped[dict | None] = mapped_column(JSONType)
    candidates_processed: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_progress_symbol: Mapped[str | None] = mapped_column(String(64))
    trigger: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    candidates: Mapped[list["ScanCandidate"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )


class ScanCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scan_candidates"
    __table_args__ = (
        UniqueConstraint("scan_id", "symbol", "direction", name="uq_candidate_scan_symbol_direction"),
        CheckConstraint("direction IN ('LONG','SHORT')", name="candidate_direction_allowed"),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','PUBLISHED','EXPIRED')",
            name="candidate_status_allowed",
        ),
        Index("ix_scan_candidates_status", "status"),
        Index("ix_scan_candidates_direction_score", "direction", "score"),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    scan_ltp: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    grade: Mapped[str] = mapped_column(String(4), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CandidateStatus.PENDING.value
    )

    scan: Mapped[ScanRun] = relationship(back_populates="candidates")
    signal: Mapped[Optional["PublishedSignal"]] = relationship(  # noqa: F821
        back_populates="candidate", uselist=False
    )
