"""FastAPI dependencies: authentication, roles and collector tokens."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import constant_time_equals, decode_token, token_digest
from app.core.timeutils import ensure_aware, utcnow
from app.db.session import get_db
from app.models.collector import CollectorToken
from app.models.enums import Role
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    payload = decode_token(credentials.credentials, "access")
    subject = payload.get("sub")
    try:
        user_id = uuid.UUID(str(subject))
    except (TypeError, ValueError) as exc:
        raise _unauthorized("Invalid token subject") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Account is disabled")
    if int(payload.get("ver", 0)) != int(user.token_version or 0):
        raise _unauthorized("Session has been revoked")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


@dataclass
class CollectorContext:
    name: str
    token_id: uuid.UUID | None
    bootstrap: bool = False


def require_collector(
    x_collector_token: str | None = Header(default=None, alias="X-Collector-Token"),
    db: Session = Depends(get_db),
) -> CollectorContext:
    if not x_collector_token:
        raise _unauthorized("Missing collector token")
    settings = get_settings()

    if settings.collector_bootstrap_token and constant_time_equals(
        x_collector_token, settings.collector_bootstrap_token
    ):
        return CollectorContext(name="bootstrap", token_id=None, bootstrap=True)

    digest = token_digest(x_collector_token)
    token = db.scalar(select(CollectorToken).where(CollectorToken.token_hash == digest))
    if token is None or not token.is_active or token.revoked_at is not None:
        raise _unauthorized("Collector token is invalid or revoked")

    now = utcnow()
    if token.last_seen_at is None or (
        now - ensure_aware(token.last_seen_at)
    ) > timedelta(seconds=60):
        token.last_seen_at = now
        db.commit()
    return CollectorContext(name=token.name, token_id=token.id)
