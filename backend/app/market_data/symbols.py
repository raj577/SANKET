"""Symbol mapping shared by the LTP tracker and the candle cache.

OI scan candidates carry bare underlyings (``NIFTY``, ``SBIN``), while FYERS
quotes and history need a full symbol (``NSE:NIFTY50-INDEX``, ``NSE:SBIN-EQ``).
Keeping the mapping in one place means the performance analysis cannot drift
from the symbols the tracker already uses.
"""
from __future__ import annotations

INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:NIFTYMIDCAP150-INDEX",
    "NIFTYNXT50": "NSE:NIFTYNXT50-INDEX",
}


def to_fyers_symbol(symbol: str) -> str:
    """Map a bare underlying (or an already-qualified symbol) to FYERS form."""
    name = str(symbol or "").strip().upper()
    if ":" in name:
        return name
    if name in INDEX_SYMBOLS:
        return INDEX_SYMBOLS[name]
    return f"NSE:{name}-EQ"


def identity_symbol(symbol: str) -> str:
    """Kotak quotes use the plain NSE symbol, not a ``NSE:...`` string."""
    return str(symbol or "").strip().upper()


__all__ = ["INDEX_SYMBOLS", "identity_symbol", "to_fyers_symbol"]
