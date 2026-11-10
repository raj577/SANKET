"""Password hashing and JWT helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.core.exceptions import AuthError

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except ValueError:
        return False


def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    token_version: int = 0,
    **claims: Any,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "ver": int(token_version),
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": secrets.token_hex(16),
        **claims,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str, token_version: int = 0) -> str:
    settings = get_settings()
    return _create_token(
        user_id,
        ACCESS_TOKEN_TYPE,
        timedelta(minutes=settings.access_token_minutes),
        token_version,
        role=role,
    )


def create_refresh_token(user_id: str, role: str, token_version: int = 0) -> str:
    settings = get_settings()
    return _create_token(
        user_id,
        REFRESH_TOKEN_TYPE,
        timedelta(days=settings.refresh_token_days),
        token_version,
        role=role,
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise AuthError("Wrong token type")
    return payload


def token_digest(token: str) -> str:
    """Stable digest used to store refresh and collector tokens at rest."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
