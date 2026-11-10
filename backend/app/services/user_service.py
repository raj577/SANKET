"""User, refresh-token and password workflow."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthError, ConflictError, NotFoundError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_digest,
    verify_password,
)
from app.core.timeutils import ensure_aware, utcnow
from app.models.enums import Role
from app.models.user import RefreshToken, User


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _store_refresh(db: Session, user: User, refresh_token: str) -> None:
    settings = get_settings()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_digest(refresh_token),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        )
    )


def issue_tokens(db: Session, user: User) -> TokenPair:
    version = int(user.token_version or 0)
    access = create_access_token(str(user.id), user.role, version)
    refresh = create_refresh_token(str(user.id), user.role, version)
    _store_refresh(db, user, refresh)
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    if not user.is_active:
        raise AuthError("Account is disabled")
    return user


def rotate_refresh_token(db: Session, refresh_token: str) -> TokenPair:
    decode_token(refresh_token, "refresh")
    digest = token_digest(refresh_token)
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest))
    if stored is None:
        raise AuthError("Refresh token is not recognised")
    if stored.revoked_at is not None:
        # Reuse of a rotated token is suspicious: revoke every active session
        # for this account so a stolen token cannot keep refreshing.
        now = utcnow()
        user = db.get(User, stored.user_id)
        if user is not None:
            user.token_version = int(user.token_version or 0) + 1
        active = db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == stored.user_id,
                RefreshToken.revoked_at.is_(None),
            )
        ).all()
        for token in active:
            token.revoked_at = now
        db.commit()
        raise AuthError("Refresh token has been revoked")
    if ensure_aware(stored.expires_at) < utcnow():
        raise AuthError("Refresh token has expired")

    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthError("Account is disabled")

    stored.revoked_at = utcnow()
    version = int(user.token_version or 0)
    access = create_access_token(str(user.id), user.role, version)
    new_refresh = create_refresh_token(str(user.id), user.role, version)
    new_payload = decode_token(new_refresh, "refresh")
    stored.replaced_by = new_payload.get("jti")
    _store_refresh(db, user, new_refresh)
    db.commit()
    return TokenPair(access_token=access, refresh_token=new_refresh)


def logout_session(db: Session, refresh_token: str) -> None:
    """End every session for the account that owns this refresh token.

    Access tokens are stateless, so clearing cookies is not enough; bumping the
    user's token version invalidates every access token already issued, and all
    stored refresh tokens are revoked as well.
    """
    try:
        decode_token(refresh_token, "refresh")
    except AuthError:
        return
    digest = token_digest(refresh_token)
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest))
    if stored is None:
        return
    user = db.get(User, stored.user_id)
    if user is None:
        return
    now = utcnow()
    user.token_version = int(user.token_version or 0) + 1
    active = db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
        )
    ).all()
    for token in active:
        token.revoked_at = now
    db.commit()


def get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def create_user(
    db: Session,
    *,
    name: str,
    email: str,
    password: str,
    role: Role | str = Role.USER,
) -> User:
    settings = get_settings()
    email = email.strip().lower()
    if len(password) < settings.password_min_length:
        raise ValidationError(
            f"Password must be at least {settings.password_min_length} characters"
        )
    if get_user_by_email(db, email) is not None:
        raise ConflictError("A user with this email already exists")
    role_value = role.value if isinstance(role, Role) else str(role)
    if role_value not in {Role.ADMIN.value, Role.USER.value}:
        raise ValidationError("Role must be ADMIN or USER")
    user = User(
        name=name.strip() or email,
        email=email,
        password_hash=hash_password(password),
        role=role_value,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_bootstrap_admin(db: Session) -> User | None:
    settings = get_settings()
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        return None
    existing = get_user_by_email(db, settings.bootstrap_admin_email)
    if existing is not None:
        return existing
    return create_user(
        db,
        name=settings.bootstrap_admin_name,
        email=settings.bootstrap_admin_email,
        password=settings.bootstrap_admin_password,
        role=Role.ADMIN,
    )


def list_users(db: Session, offset: int, limit: int) -> tuple[list[User], int]:
    total = db.scalar(select(func.count(User.id))) or 0
    users = db.scalars(select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)).all()
    return list(users), int(total)


def update_user(
    db: Session,
    user_id: uuid.UUID,
    *,
    name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> User:
    user = get_user(db, user_id)
    removing_admin = user.role == Role.ADMIN.value and (
        (role is not None and role != Role.ADMIN.value) or is_active is False
    )
    if removing_admin:
        active_admins = db.scalar(
            select(func.count(User.id)).where(
                User.role == Role.ADMIN.value, User.is_active.is_(True)
            )
        ) or 0
        if active_admins <= 1:
            raise ConflictError("At least one active administrator must remain")
    if name is not None:
        user.name = name.strip() or user.name
    if role is not None:
        if role not in {Role.ADMIN.value, Role.USER.value}:
            raise ValidationError("Role must be ADMIN or USER")
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if password:
        settings = get_settings()
        if len(password) < settings.password_min_length:
            raise ValidationError(
                f"Password must be at least {settings.password_min_length} characters"
            )
        user.password_hash = hash_password(password)
        # A password reset must end every existing session.
        user.token_version = int(user.token_version or 0) + 1
        now = utcnow()
        active = db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
        ).all()
        for token in active:
            token.revoked_at = now
    db.commit()
    db.refresh(user)
    return user
