"""Signal price tracking and threshold detection.

Only the first observed threshold crossing is recorded. When price updates were
interrupted, the crossing is attributed to the observation time, never to a
fabricated earlier time.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.timeutils import utcnow
from app.models.enums import Direction, PriceEventType, SignalStatus
from app.models.signal import PublishedSignal, SignalPriceHistory

TARGET_HIT = SignalStatus.TARGET_HIT.value
STOPLOSS_HIT = SignalStatus.STOPLOSS_HIT.value


def evaluate_threshold(
    direction: str, ltp: Decimal | float, target: Decimal | float | None, stop_loss: Decimal | float | None
) -> str | None:
    ltp = Decimal(str(ltp))
    if target is not None:
        target_d = Decimal(str(target))
        if direction == Direction.LONG.value and ltp >= target_d:
            return TARGET_HIT
        if direction == Direction.SHORT.value and ltp <= target_d:
            return TARGET_HIT
    if stop_loss is not None:
        stop_d = Decimal(str(stop_loss))
        if direction == Direction.LONG.value and ltp <= stop_d:
            return STOPLOSS_HIT
        if direction == Direction.SHORT.value and ltp >= stop_d:
            return STOPLOSS_HIT
    return None


def apply_price_tick(
    db: Session,
    signal: PublishedSignal,
    ltp: Decimal | float,
    *,
    captured_at: datetime | None = None,
    persist_interval_seconds: int = 60,
    persist_snapshot: bool = True,
) -> dict:
    """Apply one observed LTP to a signal.

    Returns a dict describing the event and whether any row changed.
    """
    observed_at = captured_at or utcnow()
    value = Decimal(str(ltp))

    # Terminal signals are no longer tracked; their closing observation stands.
    if signal.status != SignalStatus.ACTIVE.value:
        return {"event": None, "changed": False, "status": signal.status}

    changed = False
    if signal.current_ltp != value:
        signal.current_ltp = value
        signal.price_updated_at = observed_at
        changed = True

    event = evaluate_threshold(signal.direction, value, signal.target_price, signal.stop_loss)
    if event is not None:
        signal.status = event
        signal.closed_at = observed_at
        if event == TARGET_HIT:
            signal.target_hit_at = observed_at
        else:
            signal.stoploss_hit_at = observed_at
        db.add(
            SignalPriceHistory(
                signal_id=signal.id,
                ltp=value,
                captured_at=observed_at,
                event_type=event,
            )
        )
        db.commit()
        db.refresh(signal)
        return {"event": event, "changed": True, "status": signal.status}

    if persist_snapshot:
        last = (
            db.query(SignalPriceHistory)
            .filter(SignalPriceHistory.signal_id == signal.id)
            .order_by(SignalPriceHistory.captured_at.desc())
            .first()
        )
        should_persist = (
            changed
            and (
                last is None
                or (observed_at - last.captured_at).total_seconds() >= persist_interval_seconds
            )
        )
        if should_persist:
            db.add(
                SignalPriceHistory(
                    signal_id=signal.id,
                    ltp=value,
                    captured_at=observed_at,
                    event_type=PriceEventType.SNAPSHOT.value,
                )
            )
    if changed:
        db.commit()
    return {"event": None, "changed": changed, "status": signal.status}
