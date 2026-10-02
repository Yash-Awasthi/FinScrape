"""Ingest stores the API's analysis for new events, skipping heuristic answers."""

import asyncio

from worker import runner


def test_precompute_stores_real_answers_and_skips_heuristics(monkeypatch):
    saved: dict[int, dict] = {}

    async def get_event(pool, eid):
        return {"id": eid} if eid != 3 else None

    def analyze(event):
        if event["id"] == 2:
            return {"summary": "h", "ticker_impacts": [], "heuristic": True}
        return {"summary": f"real {event['id']}", "ticker_impacts": []}

    async def save(pool, key, eid, result):
        saved[eid] = result

    monkeypatch.setattr(runner, "get_event_by_id", get_event)
    monkeypatch.setattr(runner, "analyze_event", analyze)
    monkeypatch.setattr(runner, "save_ai_cache", save)
    stored = asyncio.run(runner.precompute_analysis(None, [1, 2, 3]))
    assert stored == 1 and list(saved) == [1]
