"""Repeat history for OI candidates across scans and scan days.

The candidates page asks three review questions about every row:

* did the same stock also pass the immediately previous OI scan? ("last 2 scans")
* did it pass a scan on one of the two previous scan days? ("last 2 scan days")
* was its latest direction there SHORT while this row is LONG? (a flip)

All comparisons are relative to the row's own scan, so the answers stay correct
whether the page shows the latest scan or an older one. Only OI scans take part:
pattern candidates carry no direction and live in another table.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.core.timeutils import to_ist
from app.models.enums import ScanType
from app.models.scan import ScanCandidate, ScanRun

REPEAT_LAST_2_SCANS = "last_2_scans"
REPEAT_LAST_2_DAYS = "last_2_days"
REPEAT_SHORT_TO_LONG = "short_to_long"
REPEAT_FILTERS = (
    REPEAT_LAST_2_SCANS,
    REPEAT_LAST_2_DAYS,
    REPEAT_SHORT_TO_LONG,
)


@dataclass(frozen=True)
class _ScanContext:
    """Where one scan sits relative to the scans that came before it."""

    previous_scan_id: uuid.UUID | None
    #: Scans from the two most recent earlier scan days, oldest first.
    previous_day_scan_ids: tuple[uuid.UUID, ...]


def resolve_repeat_filter(value: str | None) -> str | None:
    """Validate the repeat filter, or ``None`` when the page shows everything."""
    if value is None or not value.strip():
        return None
    choice = value.strip().lower()
    if choice not in REPEAT_FILTERS:
        raise ValidationError(f"repeat must be one of: {', '.join(REPEAT_FILTERS)}")
    return choice


def matches(history: dict[str, Any], repeat: str) -> bool:
    if repeat == REPEAT_LAST_2_SCANS:
        return bool(history["in_previous_scan"])
    if repeat == REPEAT_LAST_2_DAYS:
        return bool(history["in_last_2_days"])
    if repeat == REPEAT_SHORT_TO_LONG:
        return bool(history["short_to_long"])
    raise ValidationError(f"repeat must be one of: {', '.join(REPEAT_FILTERS)}")


def _scan_rows(db: Session) -> list[tuple[uuid.UUID, datetime]]:
    rows = db.execute(
        select(ScanRun.id, ScanRun.started_at)
        .where(ScanRun.scan_type == ScanType.OI.value)
        .order_by(ScanRun.started_at.asc(), ScanRun.id.asc())
    ).all()
    return [(row.id, row.started_at) for row in rows]


def _scan_contexts(
    scan_rows: list[tuple[uuid.UUID, datetime]],
) -> dict[uuid.UUID, _ScanContext]:
    """Map every scan to its previous scan and its previous two scan days."""
    scans_by_day: dict[date, list[uuid.UUID]] = defaultdict(list)
    day_of: dict[uuid.UUID, date] = {}
    for scan_id, started_at in scan_rows:
        day = to_ist(started_at).date()
        day_of[scan_id] = day
        scans_by_day[day].append(scan_id)

    days = sorted(scans_by_day)
    day_index = {day: index for index, day in enumerate(days)}

    contexts: dict[uuid.UUID, _ScanContext] = {}
    for index, (scan_id, _started_at) in enumerate(scan_rows):
        earlier_days = days[max(0, day_index[day_of[scan_id]] - 2) : day_index[day_of[scan_id]]]
        contexts[scan_id] = _ScanContext(
            previous_scan_id=scan_rows[index - 1][0] if index else None,
            previous_day_scan_ids=tuple(
                earlier_scan for day in earlier_days for earlier_scan in scans_by_day[day]
            ),
        )
    return contexts


def _directions_by_scan(
    db: Session, scan_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, dict[str, frozenset[str]]]:
    """symbol -> the set of directions it had in each referenced scan."""
    wanted = list(dict.fromkeys(scan_ids))
    if not wanted:
        return {}
    rows = db.execute(
        select(
            ScanCandidate.scan_id,
            ScanCandidate.symbol,
            ScanCandidate.direction,
        ).where(ScanCandidate.scan_id.in_(wanted))
    ).all()
    found: dict[uuid.UUID, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        found[row.scan_id][row.symbol].add(row.direction)
    return {
        scan_id: {symbol: frozenset(directions) for symbol, directions in symbols.items()}
        for scan_id, symbols in found.items()
    }


def history_map(
    db: Session, candidates: Iterable[Any]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Compute repeat flags for ``candidates`` (ORM rows or lean id/scan/symbol rows)."""
    rows = list(candidates)
    if not rows:
        return {}

    scan_rows = _scan_rows(db)
    contexts = _scan_contexts(scan_rows)
    started_at = dict(scan_rows)

    needed_scans: set[uuid.UUID] = set()
    for row in rows:
        context = contexts.get(row.scan_id)
        if context is None:
            continue
        if context.previous_scan_id is not None:
            needed_scans.add(context.previous_scan_id)
        needed_scans.update(context.previous_day_scan_ids)
    directions = _directions_by_scan(db, needed_scans)

    histories: dict[uuid.UUID, dict[str, Any]] = {}
    for row in rows:
        histories[row.id] = _history_for_row(
            row, contexts, directions, started_at
        )
    return histories


def _history_for_row(
    row: Any,
    contexts: dict[uuid.UUID, _ScanContext],
    directions: dict[uuid.UUID, dict[str, frozenset[str]]],
    started_at: dict[uuid.UUID, datetime],
) -> dict[str, Any]:
    history: dict[str, Any] = {
        "in_previous_scan": False,
        "in_last_2_days": False,
        "previous_direction": None,
        "short_to_long": False,
        "previous_seen_at": None,
    }
    context = contexts.get(row.scan_id)
    if context is None:
        return history

    if context.previous_scan_id is not None:
        previous = directions.get(context.previous_scan_id, {})
        if row.symbol in previous:
            history["in_previous_scan"] = True
            history["previous_seen_at"] = started_at[context.previous_scan_id]

    seen_at: datetime | None = history["previous_seen_at"]
    latest_direction: frozenset[str] | None = None
    for scan_id in context.previous_day_scan_ids:
        found = directions.get(scan_id, {}).get(row.symbol)
        if not found:
            continue
        history["in_last_2_days"] = True
        latest_direction = found
        scan_started = started_at[scan_id]
        if seen_at is None or scan_started > seen_at:
            seen_at = scan_started

    if latest_direction is not None and len(latest_direction) == 1:
        history["previous_direction"] = next(iter(latest_direction))
    history["previous_seen_at"] = seen_at
    history["short_to_long"] = (
        row.direction == "LONG" and history["previous_direction"] == "SHORT"
    )
    return history


__all__ = [
    "REPEAT_FILTERS",
    "REPEAT_LAST_2_DAYS",
    "REPEAT_LAST_2_SCANS",
    "REPEAT_SHORT_TO_LONG",
    "history_map",
    "matches",
    "resolve_repeat_filter",
]
