"""Classification of provider failures, shared by every FYERS consumer.

FYERS signals an auth problem and its per-minute plan limit through the message
text rather than a stable error code, so this logic has to stay in one place:
the pattern scanner, the candle backfill and the LTP tracker must all agree on
which errors are fatal and which are worth retrying.
"""
from __future__ import annotations


def is_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        part in text
        for part in (
            "access token",
            "invalid token",
            "token expired",
            "token has expired",
            "unauthor",
            "authenticate",
            "authentication",
            "invalid client",
            "please login",
            "session expired",
        )
    )


def is_rate_limit_error(exc: BaseException) -> bool:
    """Detect FYERS' per-minute plan limit, whatever shape the error takes."""
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "requests/minute" in text


__all__ = ["is_auth_error", "is_rate_limit_error"]
