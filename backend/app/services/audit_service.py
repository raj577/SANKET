"""Administrator audit logging."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.audit import AdminAuditLog
from app.models.user import User


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: dict | None = None,
    user: User | None = None,
) -> AdminAuditLog:
    log = AdminAuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
    )
    db.add(log)
    return log
