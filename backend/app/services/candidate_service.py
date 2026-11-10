"""Candidate review workflow (approve / reject)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import AuditAction, CandidateStatus
from app.models.scan import ScanCandidate
from app.models.user import User
from app.services import audit_service


def get_candidate(db: Session, candidate_id: uuid.UUID) -> ScanCandidate:
    candidate = db.get(ScanCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("Candidate not found")
    return candidate


def list_candidates(
    db: Session,
    *,
    scan_id: uuid.UUID | None = None,
    direction: str | None = None,
    status: str | None = None,
    grade: str | None = None,
    symbol: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[ScanCandidate], int]:
    stmt = select(ScanCandidate)
    count_stmt = select(func.count(ScanCandidate.id))
    conditions = []
    if scan_id:
        conditions.append(ScanCandidate.scan_id == scan_id)
    if direction:
        conditions.append(ScanCandidate.direction == direction.upper())
    if status:
        conditions.append(ScanCandidate.status == status.upper())
    if grade:
        conditions.append(ScanCandidate.grade == grade)
    if symbol:
        conditions.append(ScanCandidate.symbol.ilike(f"%{symbol.strip().upper()}%"))
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(ScanCandidate.score.desc(), ScanCandidate.symbol.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), int(total)


def approve(db: Session, candidate_id: uuid.UUID, user: User) -> ScanCandidate:
    candidate = get_candidate(db, candidate_id)
    if candidate.status in {CandidateStatus.PUBLISHED.value, CandidateStatus.EXPIRED.value}:
        raise ConflictError("A published or expired candidate cannot be approved")
    if candidate.status == CandidateStatus.APPROVED.value:
        return candidate
    previous = candidate.status
    candidate.status = CandidateStatus.APPROVED.value
    audit_service.record(
        db,
        action=AuditAction.CANDIDATE_APPROVED.value,
        entity_type="scan_candidate",
        entity_id=str(candidate.id),
        details={"symbol": candidate.symbol, "direction": candidate.direction, "from": previous},
        user=user,
    )
    db.commit()
    db.refresh(candidate)
    return candidate


def reject(db: Session, candidate_id: uuid.UUID, user: User, reason: str | None = None) -> ScanCandidate:
    candidate = get_candidate(db, candidate_id)
    if candidate.status == CandidateStatus.PUBLISHED.value:
        raise ConflictError("A published candidate cannot be rejected")
    if candidate.status == CandidateStatus.REJECTED.value:
        return candidate
    previous = candidate.status
    candidate.status = CandidateStatus.REJECTED.value
    audit_service.record(
        db,
        action=AuditAction.CANDIDATE_REJECTED.value,
        entity_type="scan_candidate",
        entity_id=str(candidate.id),
        details={
            "symbol": candidate.symbol,
            "direction": candidate.direction,
            "from": previous,
            "reason": reason,
        },
        user=user,
    )
    db.commit()
    db.refresh(candidate)
    return candidate
