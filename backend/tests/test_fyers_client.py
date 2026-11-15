"""FYERS HTTP client payload handling (no network).

The transport is replaced by a fake ``httpx.Client`` object, so these tests only
exercise response interpretation: ``s=ok``, ``s=no_data`` and error shapes.
"""
from __future__ import annotations

import pytest

from app.market_data.fyers_client import FyersClient, FyersError


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://example.test")
            raise httpx.HTTPStatusError(
                "boom",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


class FakeHttp:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self.response


def _client(payload: dict, status_code: int = 200) -> tuple[FyersClient, FakeHttp]:
    client = FyersClient(access_token="test-token")
    client.app_id = "TESTAPP"
    fake = FakeHttp(FakeResponse(payload, status_code=status_code))
    client.client = fake  # type: ignore[assignment]
    return client, fake


def test_history_treats_no_data_as_an_empty_range():
    """``s=no_data`` means the requested window has no candles, not a failure."""
    client, http = _client({"s": "no_data", "candles": [], "message": ""})

    payload = client.history(
        "NSE:TEST26NOVFUT", resolution="60", range_from="1", range_to="2"
    )

    assert payload["s"] == "no_data"
    assert payload["candles"] == []
    assert http.calls[0]["params"]["cont_flag"] == "1"


def test_history_still_raises_for_real_errors():
    client, _ = _client(
        {"s": "error", "code": -50, "message": "Invalid symbol"}, status_code=200
    )

    with pytest.raises(FyersError, match="Invalid symbol"):
        client.history("NSE:NOPE26NOVFUT", resolution="60", range_from="1", range_to="2")


def test_error_with_blank_message_reports_the_fyers_status():
    """A blank FYERS message must not collapse into an undiagnosable string."""
    client, _ = _client({"s": "error", "code": -360, "message": ""})

    with pytest.raises(FyersError, match=r"s=error, code=-360"):
        client.history("NSE:TEST26NOVFUT", resolution="60", range_from="1", range_to="2")


def test_other_endpoints_still_reject_no_data():
    """Only history tolerates ``no_data``; the OI paths keep failing loudly."""
    client, _ = _client({"s": "no_data", "message": ""})

    with pytest.raises(FyersError, match="s=no_data"):
        client.quotes(["NSE:NIFTY50-INDEX"])
