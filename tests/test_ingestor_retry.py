"""Transient-throttle retry in BaseIngestor.fetch_raw (no network, no real sleeps).

GDELT — the highest-volume source in the registry — alternates 429 and 200 within
seconds. One un-retried 429 used to cost a whole scrape cycle's articles.
"""

from __future__ import annotations

from curl_cffi.requests.exceptions import HTTPError, Timeout

from finscrape.ingestors import base
from finscrape.ingestors.base import BaseIngestor, RawGeoEvent


class Probe(BaseIngestor):
    name = "probe"
    base_url = "https://example.invalid/api"

    def parse(self, data):
        return [RawGeoEvent(title=str(data), text="", source="probe")]


class FakeResponse:
    def __init__(self, status: int, payload=None, headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else {"ok": True}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(f"{self.status_code} error")

    def json(self):
        return self._payload


def _patch(monkeypatch, responses):
    """Serve `responses` in order; record how long the code asked to sleep."""
    calls, slept = [], []

    def fake_get(*_a, **_k):
        calls.append(1)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(base.requests, "get", fake_get)
    monkeypatch.setattr(base.time, "sleep", lambda s: slept.append(s))
    return calls, slept


def test_retries_a_429_then_succeeds(monkeypatch):
    calls, slept = _patch(
        monkeypatch, [FakeResponse(429), FakeResponse(200, {"articles": []})]
    )
    assert Probe().fetch_raw() == {"articles": []}
    assert len(calls) == 2
    assert slept  # backed off before the retry


def test_gives_up_after_the_retry_budget(monkeypatch):
    calls, _ = _patch(monkeypatch, [FakeResponse(429)])
    assert Probe().fetch_raw() is None
    assert len(calls) == base._RETRIES + 1


def test_does_not_retry_a_settled_failure(monkeypatch):
    """410 Gone (decommissioned API) and 403 (unapproved appname) will never succeed;
    retrying only delays the log line."""
    for status in (403, 410, 404):
        calls, slept = _patch(monkeypatch, [FakeResponse(status)])
        assert Probe().fetch_raw() is None
        assert len(calls) == 1, f"{status} should not retry"
        assert slept == []


def test_honours_retry_after_but_caps_it(monkeypatch):
    _, slept = _patch(
        monkeypatch,
        [FakeResponse(429, headers={"Retry-After": "900"}), FakeResponse(200)],
    )
    Probe().fetch_raw()
    assert slept == [base._MAX_RETRY_AFTER_S]  # not 900 — longer than a scrape cycle


def test_ignores_a_nonsense_retry_after(monkeypatch):
    _, slept = _patch(
        monkeypatch,
        [
            FakeResponse(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            FakeResponse(200),
        ],
    )
    Probe().fetch_raw()
    assert slept == [base._BACKOFF_S]  # falls back to exponential backoff


def test_retries_a_timeout(monkeypatch):
    calls = []

    def flaky(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            raise Timeout("slow upstream")
        return FakeResponse(200, {"articles": [1]})

    monkeypatch.setattr(base.requests, "get", flaky)
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)
    assert Probe().fetch_raw() == {"articles": [1]}
