"""Published signal and price history models."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SignalStatus


class PublishedSignal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "published_signals"
    __table_args__ = (
        CheckConstraint("direction IN ('LONG','SHORT')", name="signal_direction_allowed"),
        CheckConstraint(
            "status IN ('ACTIVE','TARGET_HIT','STOPLOSS_HIT','EXPIRED','CANCELLED')",
            name="signal_status_allowed",
        ),
        Index("ix_published_signals_status", "status"),
        Index("ix_published_signals_symbol", "symbol"),
        Index("ix_published_signals_published_at", "published_at"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("scan_candidates.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    scan_ltp: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    target_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    current_ltp: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    target_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stoploss_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SignalStatus.ACTIVE.value
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    candidate: Mapped["ScanCandidate"] = relationship(back_populates="signal")  # noqa: F821
    price_history: Mapped[list["SignalPriceHistory"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan"
    )


class SignalPriceHistory(Base):
    __tablename__ = "signal_price_history"
    __table_args__ = (
        Index("ix_signal_price_history_signal_captured", "signal_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("published_signals.id", ondelete="CASCADE"), nullable=False
    )
    ltp: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)

    signal: Mapped[PublishedSignal] = relationship(back_populates="price_history")
