"""Market-data provider configuration status."""
from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def provider_status() -> tuple[str, bool, bool]:
    """Return ``(provider, configured, stream_ready)``.

    Kotak quotes/scrip master need only the consumer key; the SFeed websocket
    additionally needs mobile number, UCC, MPIN and the TOTP secret.
    """
    settings = get_settings()
    provider = (settings.market_data_provider or "fyers").lower()
    if provider == "kotak":
        configured = bool(settings.kotak_consumer_key)
        stream_ready = configured and all(
            [
                settings.kotak_mobile_number,
                settings.kotak_ucc,
                settings.kotak_mpin,
                settings.kotak_totp_secret,
            ]
        )
        return provider, configured, stream_ready
    configured = bool(settings.fyers_app_id) and (
        bool(settings.fyers_access_token) or Path(settings.fyers_token_file).is_file()
    )
    return provider, configured, configured
