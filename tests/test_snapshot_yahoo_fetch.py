from __future__ import annotations

import asyncio

import httpx

from snapshot_collector import (
    IndexData,
    _collect_index_results,
    _fetch_yahoo_chart_data,
)


class _MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> dict:
        return self._payload


class _MockYahooClient:
    def __init__(self, responses: list[_MockResponse]):
        self._responses = responses
        self.calls: list[dict] = []

    async def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self._responses.pop(0)


def test_fetch_yahoo_chart_data_retries_after_429(monkeypatch):
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1710460800, 1710547200],
                    "indicators": {"quote": [{"close": [5100.25, 5200.75]}]},
                }
            ],
            "error": None,
        }
    }
    client = _MockYahooClient(
        [
            _MockResponse(429, {}),
            _MockResponse(200, payload),
        ]
    )

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("snapshot_collector.asyncio.sleep", _fake_sleep)

    label, data, error = asyncio.run(_fetch_yahoo_chart_data(client, "S&P500", ["^GSPC"]))

    assert label == "S&P500"
    assert error is None
    assert isinstance(data, IndexData)
    assert data.close == 5200.75
    assert len(client.calls) == 2
    assert sleep_calls


def test_collect_index_results_fetches_in_defined_order(monkeypatch):
    call_order: list[str] = []

    async def _fake_fetch_index_data(client, label: str):
        call_order.append(label)
        return label, None, f"{label} unavailable"

    monkeypatch.setattr("snapshot_collector._fetch_index_data", _fake_fetch_index_data)

    results = asyncio.run(_collect_index_results(client=object()))

    assert [label for label, _, _ in results] == call_order
    assert call_order == ["S&P500", "Nasdaq100", "Dow", "VIX", "USDJPY"]
