"""Encrypted on-disk storage for the FYERS access token.

The token never touches disk in plaintext: :class:`~cryptography.fernet.Fernet`
encrypts a small JSON document before it is written. The key is read from
``FYERS_TOKEN_ENCRYPTION_KEY`` and must stay stable across restarts, otherwise
the stored token is unreadable and the administrator has to log in again.

This module intentionally refuses to fall back to plaintext. If the key is
missing or malformed, saving raises :class:`FyersTokenStoreError` and the API
reports that token storage is not configured.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timeutils import ensure_aware, utcnow

logger = get_logger(__name__)

FILE_VERSION = 1
#: Fraction of the remaining lifetime below which the status endpoint asks for
#: a re-login before the token actually dies (FYERS tokens expire daily).
REAUTH_WARNING_SECONDS = 15 * 60


class FyersTokenStoreError(RuntimeError):
    """The encrypted token cannot be written, decrypted or is misconfigured."""


def generate_key() -> str:
    """Return a fresh Fernet key suitable for ``FYERS_TOKEN_ENCRYPTION_KEY``."""
    return Fernet.generate_key().decode("ascii")


def encryption_key_configured() -> bool:
    return bool((get_settings().fyers_token_encryption_key or "").strip())


def _fernet() -> Fernet:
    key = (get_settings().fyers_token_encryption_key or "").strip()
    if not key:
        raise FyersTokenStoreError(
            "FYERS_TOKEN_ENCRYPTION_KEY is not configured; the FYERS token is never stored in plaintext"
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise FyersTokenStoreError(
            "FYERS_TOKEN_ENCRYPTION_KEY is not a valid Fernet key"
        ) from exc


def _jwt_expiry(access_token: str) -> datetime | None:
    """Read the ``exp`` claim of a FYERS access token without trusting it.

    The value is only used for status reporting; FYERS still validates the
    token on every request, so an unverified signature cannot grant access.
    """
    try:
        claims = jwt.decode(
            access_token,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
        )
    except jwt.PyJWTError:
        return None
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(float(exp), tz=timezone.utc)


def resolve_expiry(
    access_token: str,
    *,
    expires_in: float | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """Best available expiry for a freshly issued token.

    Preference order: explicit ``expires_in`` from FYERS, then the JWT ``exp``
    claim, then ``FYERS_TOKEN_ASSUMED_TTL_SECONDS``. ``None`` means "unknown",
    which is reported as a token of unverified validity rather than as expired.
    """
    issued = ensure_aware(now or utcnow())
    if expires_in is not None:
        try:
            seconds = int(expires_in)
        except (TypeError, ValueError):
            seconds = 0
        if seconds > 0:
            return issued + timedelta(seconds=seconds)
    from_token = _jwt_expiry(access_token)
    if from_token is not None:
        return from_token
    assumed = int(get_settings().fyers_token_assumed_ttl_seconds or 0)
    if assumed > 0:
        return issued + timedelta(seconds=assumed)
    return None


@dataclass(frozen=True)
class FyersTokenRecord:
    """Decrypted token plus the metadata the status endpoint reports."""

    access_token: str
    authenticated_at: datetime
    expires_at: datetime | None = None
    source: str = "unknown"
    app_id: str | None = None

    def seconds_remaining(self, now: datetime | None = None) -> int | None:
        if self.expires_at is None:
            return None
        delta = ensure_aware(self.expires_at) - ensure_aware(now or utcnow())
        return int(delta.total_seconds())

    def is_expired(self, now: datetime | None = None) -> bool:
        remaining = self.seconds_remaining(now)
        return remaining is not None and remaining <= 0

    def is_valid(self, now: datetime | None = None) -> bool:
        return not self.is_expired(now)

    def expires_soon(self, now: datetime | None = None) -> bool:
        remaining = self.seconds_remaining(now)
        return remaining is not None and 0 < remaining <= REAUTH_WARNING_SECONDS

    def to_dict(self) -> dict:
        return {
            "version": FILE_VERSION,
            "access_token": self.access_token,
            "authenticated_at": ensure_aware(self.authenticated_at).isoformat(),
            "expires_at": ensure_aware(self.expires_at).isoformat() if self.expires_at else None,
            "source": self.source,
            "app_id": self.app_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FyersTokenRecord:
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise FyersTokenStoreError("Stored FYERS token is empty or malformed")
        expires_raw = data.get("expires_at")
        authenticated_raw = data.get("authenticated_at")
        if not authenticated_raw:
            raise FyersTokenStoreError("Stored FYERS token has no authentication timestamp")
        try:
            authenticated_at = ensure_aware(datetime.fromisoformat(str(authenticated_raw)))
            expires_at = (
                ensure_aware(datetime.fromisoformat(str(expires_raw))) if expires_raw else None
            )
        except ValueError as exc:
            raise FyersTokenStoreError("Stored FYERS token has invalid timestamps") from exc
        return cls(
            access_token=token,
            authenticated_at=authenticated_at,
            expires_at=expires_at,
            source=str(data.get("source") or "unknown"),
            app_id=data.get("app_id"),
        )


@dataclass(frozen=True)
class FyersTokenStatus:
    """Secret-free view of the stored credential."""

    token_file: str
    encryption_configured: bool
    credentials_configured: bool
    token_present: bool
    token_valid: bool
    expires_at: datetime | None = None
    authenticated_at: datetime | None = None
    seconds_remaining: int | None = None
    source: str | None = None
    error: str | None = None

    @property
    def reauth_required(self) -> bool:
        return not (self.token_present and self.token_valid)

    @property
    def expires_soon(self) -> bool:
        remaining = self.seconds_remaining
        return remaining is not None and 0 < remaining <= REAUTH_WARNING_SECONDS

    def as_dict(self) -> dict:
        return {
            "token_file": self.token_file,
            "encryption_configured": self.encryption_configured,
            "credentials_configured": self.credentials_configured,
            "token_present": self.token_present,
            "token_valid": self.token_valid,
            "expires_at": self.expires_at,
            "authenticated_at": self.authenticated_at,
            "seconds_remaining": self.seconds_remaining,
            "source": self.source,
            "reauth_required": self.reauth_required,
            "expires_soon": self.expires_soon,
            "error": self.error,
        }


class FyersTokenStore:
    """Fernet-encrypted token file, e.g. ``storage/fyers_token.bin``."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or settings.fyers_token_file)

    # -- write ------------------------------------------------------------
    def save(
        self,
        access_token: str,
        *,
        expires_at: datetime | None = None,
        expires_in: float | None = None,
        source: str = "oauth_callback",
        app_id: str | None = None,
        now: datetime | None = None,
    ) -> FyersTokenRecord:
        if not access_token or not access_token.strip():
            raise FyersTokenStoreError("Refusing to store an empty FYERS access token")
        settings = get_settings()
        authenticated_at = ensure_aware(now or utcnow())
        record = FyersTokenRecord(
            access_token=access_token.strip(),
            authenticated_at=authenticated_at,
            expires_at=ensure_aware(expires_at)
            if expires_at is not None
            else resolve_expiry(access_token, expires_in=expires_in, now=authenticated_at),
            source=source,
            app_id=app_id or settings.fyers_app_id,
        )

        blob = _fernet().encrypt(json.dumps(record.to_dict()).encode("utf-8"))

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:  # pragma: no cover - Windows best effort
            pass

        tmp = self.path.with_name(f"{self.path.name}.tmp")
        with open(tmp, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - Windows best effort
            pass
        return record

    # -- read -------------------------------------------------------------
    def load_record(self) -> FyersTokenRecord | None:
        """Return the decrypted record, ``None`` if absent. Raises on corruption."""
        if not self.path.is_file():
            return None
        raw = self.path.read_bytes()
        if not raw:
            return None
        if raw.lstrip()[:1] == b"{":
            # Pre-v3.4 installs wrote plaintext JSON. Never read it: treat it as
            # absent and let the administrator authenticate again.
            raise FyersTokenStoreError(
                "Legacy plaintext FYERS token found and ignored; log in again to store an encrypted token"
            )
        try:
            plaintext = _fernet().decrypt(raw)
        except InvalidToken as exc:
            raise FyersTokenStoreError(
                "Stored FYERS token cannot be decrypted; FYERS_TOKEN_ENCRYPTION_KEY changed or the file is corrupt"
            ) from exc
        try:
            data = json.loads(plaintext)
        except ValueError as exc:
            raise FyersTokenStoreError("Stored FYERS token payload is not valid JSON") from exc
        return FyersTokenRecord.from_dict(data)

    def load(self) -> str | None:
        """Return the raw access token or ``None``. Never raises.

        Used by the market-data clients, where a missing token simply means
        "not configured"; the status endpoint reports the reason separately.
        """
        try:
            record = self.load_record()
        except FyersTokenStoreError as exc:
            logger.warning("fyers_token_unreadable", extra={"reason": str(exc)})
            return None
        return record.access_token if record else None

    def status(self) -> FyersTokenStatus:
        settings = get_settings()
        encryption_configured = encryption_key_configured()
        credentials_configured = bool(settings.fyers_app_id and settings.fyers_secret_key)
        base = {
            "token_file": str(self.path),
            "encryption_configured": encryption_configured,
            "credentials_configured": credentials_configured,
        }
        try:
            record = self.load_record()
        except FyersTokenStoreError as exc:
            return FyersTokenStatus(token_present=True, token_valid=False, error=str(exc), **base)
        if record is None:
            return FyersTokenStatus(token_present=False, token_valid=False, **base)
        now = utcnow()
        return FyersTokenStatus(
            token_present=True,
            token_valid=record.is_valid(now),
            expires_at=record.expires_at,
            authenticated_at=record.authenticated_at,
            seconds_remaining=record.seconds_remaining(now),
            source=record.source,
            **base,
        )

    def delete(self) -> bool:
        """Remove the stored token (used before a fresh login or on logout)."""
        if not self.path.is_file():
            return False
        try:
            self.path.unlink()
        except OSError as exc:  # pragma: no cover - Windows file locks
            raise FyersTokenStoreError("Could not delete the stored FYERS token") from exc
        return True
