"""When every model fails, a click starts one backup job and polls only read the cache."""

import asyncio

from server.routes import ai as route
from server.settings import get_settings


def test_failed_click_dispatches_once_and_polls_spend_no_model_calls(monkeypatch):
    model_calls: list[int] = []
    dispatches: list[dict] = []

    async def no_cache(pool, eid):
        return None

    async def event(pool, eid):
        return {"id": eid, "subject": "s", "verdict": "OBSERVE", "tickers": []}

    def analyze(ev):
        model_calls.append(ev["id"])
        return {"summary": "h", "ticker_impacts": [], "heuristic": True}

    class Reply:
        def raise_for_status(self):
            return None

    def post(url, headers, json, timeout):
        dispatches.append(json)
        return Reply()

    monkeypatch.setenv("ANALYZE_DISPATCH_REPO", "owner/repo")
    monkeypatch.setenv("ANALYZE_DISPATCH_TOKEN", "t")
    get_settings.cache_clear()
    monkeypatch.setattr(route.db, "pool", lambda: None)
    monkeypatch.setattr(route.queries, "get_ai_cache_for_event", no_cache)
    monkeypatch.setattr(route.queries, "get_event_by_id", event)
    monkeypatch.setattr(route, "analyze_event", analyze)
    monkeypatch.setattr(route.requests, "post", post)
    monkeypatch.setattr(route, "_dispatched", {})
    try:
        first = asyncio.run(route.analyze(id=7))
        poll = asyncio.run(route.analyze(id=7))
    finally:
        get_settings.cache_clear()
    assert first["pending"] and poll["pending"]
    assert model_calls == [7]
    assert dispatches == [{"ref": "master", "inputs": {"event_id": "7"}}]


def test_dispatches_stop_at_the_hourly_cap(monkeypatch):
    sent: list[str] = []

    class Reply:
        def raise_for_status(self):
            return None

    def post(url, headers, json, timeout):
        sent.append(json["inputs"]["event_id"])
        return Reply()

    monkeypatch.setenv("ANALYZE_DISPATCH_REPO", "owner/repo")
    monkeypatch.setenv("ANALYZE_DISPATCH_TOKEN", "t")
    monkeypatch.setenv("ANALYZE_DISPATCH_PER_HOUR", "2")
    get_settings.cache_clear()
    monkeypatch.setattr(route.requests, "post", post)
    monkeypatch.setattr(route, "_dispatched", {})
    monkeypatch.setattr(route, "_recent_dispatches", route.deque())
    try:
        results = [route._dispatch_job(i) for i in (1, 2, 3)]
    finally:
        get_settings.cache_clear()
    assert results == [True, True, False]
    assert sent == ["1", "2"]
