"""Read-only FYERS data verification (no orders, no trading calls).

Run from the ``backend`` directory after completing the browser login:

    python scripts/verify_fyers.py
    python scripts/verify_fyers.py --symbol NSE:SBIN-EQ

Checks, in order: token status, authenticated profile, live quote, daily
historical candles and an option chain. Each check prints PASS/FAIL; the access
token is never printed. Exit code 0 means every check passed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.market_data.fyers_client import FyersClient, FyersError  # noqa: E402
from app.market_data.fyers_token_store import FyersTokenStore  # noqa: E402


def _line(ok: bool, label: str, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="NSE:SBIN-EQ", help="Equity symbol for quotes/history")
    parser.add_argument(
        "--chain-symbol",
        default="NSE:NIFTY50-INDEX",
        help="Underlying used for the option-chain check",
    )
    parser.add_argument("--strikes", type=int, default=5)
    args = parser.parse_args(argv)

    settings = get_settings()
    status = FyersTokenStore().status()
    print(f"token_file             : {status.token_file}")
    print(f"credentials_configured : {status.credentials_configured}")
    print(f"encryption_configured  : {status.encryption_configured}")
    print(f"token_present          : {status.token_present}")
    print(f"token_valid            : {status.token_valid}")
    print(f"expires_at             : {status.expires_at}")
    print(f"authenticated_at       : {status.authenticated_at}")
    if status.error:
        print(f"error                  : {status.error}")

    if not status.token_present or not status.token_valid:
        print(
            "\nNo usable FYERS token. Open GET /api/v1/market/fyers/login-url as an admin, "
            "complete the FYERS login, then re-run this script."
        )
        return 2

    failures = 0
    client = FyersClient()
    try:
        try:
            profile = client.profile()
            name = (profile.get("data") or {}).get("display_name") or "profile returned"
            _line(True, "authenticated profile", str(name))
        except FyersError as exc:
            failures += 1
            _line(False, "authenticated profile", str(exc))

        try:
            quotes = client.quotes([args.symbol])
            price = ((quotes[0].get("v") or {}).get("lp")) if quotes else None
            _line(bool(quotes) and price is not None, "live quote", f"{args.symbol} ltp={price}")
            if not quotes:
                failures += 1
        except FyersError as exc:
            failures += 1
            _line(False, "live quote", str(exc))

        try:
            now = int(time.time())
            history = client.history(
                args.symbol,
                resolution="D",
                range_from=str(now - 10 * 24 * 3600),
                range_to=str(now),
            )
            candles = history.get("candles") or []
            _line(bool(candles), "historical candles", f"{len(candles)} daily candles")
            if not candles:
                failures += 1
        except FyersError as exc:
            failures += 1
            _line(False, "historical candles", str(exc))

        try:
            chain = client.option_chain(args.chain_symbol, strikecount=args.strikes)
            data = chain.get("data") or {}
            strikes = len(data.get("optionsChain") or [])
            _line(
                strikes > 0,
                "option chain",
                f"{args.chain_symbol} strikes={strikes} expiry={data.get('expiryData') or 'n/a'}",
            )
            if strikes == 0:
                failures += 1
        except FyersError as exc:
            failures += 1
            _line(False, "option chain", str(exc))
    finally:
        client.close()

    print(f"\nprovider={settings.market_data_provider} scanner_provider={settings.scanner_data_provider}")
    print(f"result: {'all checks passed' if failures == 0 else f'{failures} check(s) failed'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
