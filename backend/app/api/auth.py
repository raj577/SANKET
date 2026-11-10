"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.exceptions import AuthError
from app.core.ratelimit import SlidingWindowLimiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenPairOut,
    UserOut,
)
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])

_settings = get_settings()
login_limiter = SlidingWindowLimiter(
    limit=_settings.login_rate_limit_per_minute, window_seconds=60
)


def _token_response(pair: user_service.TokenPair) -> TokenPairOut:
    return TokenPairOut(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=get_settings().access_token_minutes * 60,
    )


@router.post("/login", response_model=TokenPairOut)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenPairOut:
    # Per-account throttling also works when a trusted web proxy calls us on
    # behalf of every browser (all requests share the proxy's IP).
    limit_key = payload.email.strip().lower()
    if _settings.rate_limit_enabled and not login_limiter.allow(limit_key):
        raise AuthError("Too many login attempts. Try again shortly.", status_code=429, code="rate_limited")
    user = user_service.authenticate(db, payload.email, payload.password)
    return _token_response(user_service.issue_tokens(db, user))


@router.post("/refresh", response_model=TokenPairOut)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPairOut:
    return _token_response(user_service.rotate_refresh_token(db, payload.refresh_token))


@router.post("/logout")
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> dict:
    user_service.logout_session(db, payload.refresh_token)
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
