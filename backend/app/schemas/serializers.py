"""Response serializers that add derived, non-persisted fields."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.config import get_settings
from app.core.timeutils import ensure_aware, utcnow
from app.models.enums import SignalStatus
from app.models.signal import PublishedSignal
from app.schemas.scan import ArchiveOut, ScanOut
from app.schemas.signal import PricePointOut, SignalDetailOut, SignalOut


def _safe_percent(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator == 0:
        return None
    return float((numerator / denominator) * Decimal("100"))


def pnl_percent(signal: PublishedSignal) -> float | None:
    if signal.current_ltp is None or signal.entry_price == 0:
        return None
    entry = Decimal(str(signal.entry_price))
    current = Decimal(str(signal.current_ltp))
    if signal.direction == "LONG":
        value = ((current - entry) / entry) * Decimal("100")
    else:
        value = ((entry - current) / entry) * Decimal("100")
    return round(float(value), 4)


def target_progress_percent(signal: PublishedSignal) -> float | None:
    if signal.current_ltp is None:
        return None
    entry = Decimal(str(signal.entry_price))
    target = Decimal(str(signal.target_price))
    current = Decimal(str(signal.current_ltp))
    if target == entry:
        return None
    if signal.direction == "LONG":
        value = ((current - entry) / (target - entry)) * Decimal("100")
    else:
        value = ((entry - current) / (entry - target)) * Decimal("100")
    return round(float(value), 2)


def price_freshness(signal: PublishedSignal) -> str:
    if signal.current_ltp is None or signal.price_updated_at is None:
        return "UNKNOWN"
    settings = get_settings()
    age = (utcnow() - ensure_aware(signal.price_updated_at)).total_seconds()
    live_window = max(settings.tracking_poll_seconds * 2, 30)
    if age <= live_window:
        return "LIVE"
    if age <= max(settings.price_stale_after_seconds, live_window):
        return "DELAYED"
    return "STALE"


def signal_move_percent(signal: PublishedSignal) -> float | None:
    """Percentage from the LTP observed when the signal was generated
    (scan_ltp) to the latest observed LTP, direction-aware."""
    if signal.current_ltp is None or signal.scan_ltp == 0:
        return None
    scan = Decimal(str(signal.scan_ltp))
    current = Decimal(str(signal.current_ltp))
    if signal.direction == "LONG":
        value = ((current - scan) / scan) * Decimal("100")
    else:
        value = ((scan - current) / scan) * Decimal("100")
    return round(float(value), 4)


def target_reached(signal: PublishedSignal) -> bool:
    """True when the signal hit its target, or the observed LTP has reached it."""
    if signal.status == SignalStatus.TARGET_HIT.value:
        return True
    if signal.current_ltp is None:
        return False
    current = Decimal(str(signal.current_ltp))
    target = Decimal(str(signal.target_price))
    if signal.direction == "LONG":
        return current >= target
    if signal.direction == "SHORT":
        return current <= target
    return False


def _apply_signal_derived(out: SignalOut, signal: PublishedSignal) -> None:
    out.pnl_percent = pnl_percent(signal)
    out.target_progress_percent = target_progress_percent(signal)
    out.signal_move_percent = signal_move_percent(signal)
    out.target_reached = target_reached(signal)
    out.price_freshness = price_freshness(signal)


def signal_out(signal: PublishedSignal) -> SignalOut:
    out = SignalOut.model_validate(signal)
    _apply_signal_derived(out, signal)
    return out


def signal_detail_out(
    signal: PublishedSignal, *, price_history: list[Any] | None = None
) -> SignalDetailOut:
    out = SignalDetailOut.model_validate(signal)
    _apply_signal_derived(out, signal)
    candidate = signal.candidate
    if candidate is not None:
        out.reason = candidate.reason
        out.grade = candidate.grade
        out.score = candidate.score
        out.scan_timestamp = candidate.scanned_at
    if price_history is not None:
        out.price_history = [PricePointOut.model_validate(row) for row in price_history]
    return out


def download_url_for(scan_id) -> str | None:
    settings = get_settings()
    return f"{settings.api_v1_prefix}/admin/archives/{scan_id}/download"


def archive_out(scan) -> ArchiveOut:
    out = ArchiveOut.model_validate(
        {
            "scan_id": scan.id,
            "status": scan.status,
            "started_at": scan.started_at,
            "csv_filename": scan.csv_filename,
            "csv_storage_path": scan.csv_storage_path,
            "csv_size_bytes": scan.csv_size_bytes,
            "csv_checksum_sha256": scan.csv_checksum_sha256,
            "csv_saved_at": scan.csv_saved_at,
            "download_url": download_url_for(scan.id) if scan.csv_storage_path else None,
        }
    )
    return out


def scan_out(scan) -> ScanOut:
    return ScanOut.model_validate(scan)
