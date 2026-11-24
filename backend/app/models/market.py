"""Daily candle cache and backfill-run bookkeeping.

These tables exist only to support the day-wise performance analysis of the OI
scanner's filtered candidates. They are independent of ``scan_runs`` and of the
OI candidate schema, and they never store option-chain data.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class InstrumentCandle(Base):
    """One completed daily candle for an instrument (spot, not derivatives)."""

    __tablename__ = "instrument_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", name="uq_instrument_candles_symbol_date"),
        Index("ix_instrument_candles_trade_date", "trade_date"),
        Index("ix_instrument_candles_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    #: Full provider symbol, e.g. ``NSE:SBIN-EQ`` or ``NSE:NIFTY50-INDEX``.
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="FYERS")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CandleBackfillRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Progress record for one candle backfill job.

    Persisted (rather than kept in memory) so an admin can still see that a
    refresh ran, and where it stopped, after a server restart.
    """

    __tablename__ = "candle_backfill_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','PARTIAL','FAILED')",
            name="backfill_status_allowed",
        ),
        Index("ix_candle_backfill_runs_started_at", "started_at"),
        Index("ix_candle_backfill_runs_status", "status"),
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    range_from: Mapped[date] = mapped_column(Date, nullable=False)
    range_to: Mapped[date] = mapped_column(Date, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_symbols: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_symbols: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_symbols: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candles_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[dict | None] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def id_str(self) -> str:  # pragma: no cover - convenience only
        return str(self.id)


__all__ = ["CandleBackfillRun", "InstrumentCandle"]
