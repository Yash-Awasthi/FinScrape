"""The event page's one read (plan m4.2.1): one row by id, with its score trace.

Pure: a fake pool answers the row, so the test needs no database. The ingest half
is checked separately because a missing column there would 500 the route.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ingest import _INSERT_COLS, _insert_sql, _row_values
from server.routes import events

ROW = {
    "id": 7,
    "subject": "Exxon lifts production guidance",
    "event_type": "guidance",
    "verdict": "INVEST",
    "impact_direction": "positive",
    "signal_score": 4,
    "confidence": 0.71,
    "reasoning": "Production rose and the company raised guidance.",
    "magnitude": "high",
    "novelty": "breaking",
    "actionability": "high",
    "sector_impact": "energy",
    "tickers": ["XOM"],
    "sources": ["wire"],
    "articles": ["https://example.test/a"],
    "excerpt": "Exxon said production rose 4%. XOM guides higher.",
    "source_seen": {"wire": "2026-05-03T09:00:00+00:00"},
    "analysis_source": "model",
    "model_name": "test-model",
    "created_at": "2026-05-03T09:01:00+00:00",
    "timestamp": "2026-05-03T09:00:00+00:00",
}


class FakePool:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, sql, *args):
        return self.row


def _client(monkeypatch, row):
    app = FastAPI()
    app.include_router(events.router)
    monkeypatch.setattr(events.db, "pool", lambda: FakePool(row))
    return TestClient(app)


def test_one_event_comes_back_with_the_rules_it_passed(monkeypatch) -> None:
    body = _client(monkeypatch, ROW).get("/api/events/7").json()
    assert body["id"] == 7
    assert body["excerpt"].startswith("Exxon said")
    assert body["source_seen"] == {"wire": "2026-05-03T09:00:00+00:00"}
    # The stored +4 is the input; high magnitude + high actionability + breaking news
    # lift the rule to +5, which is why the route returns both numbers.
    assert body["score_trace"]["input"] == 4
    assert body["score_trace"]["final"] == 5
    assert any("breaking" in s for s in body["score_trace"]["steps"])
    assert body["topics"] == []  # annotate_topics still runs on the single row


def test_an_unknown_id_is_a_404_not_an_empty_row(monkeypatch) -> None:
    response = _client(monkeypatch, None).get("/api/events/404")
    assert response.status_code == 404
    assert response.json()["detail"] == "event not found"


def test_ingest_carries_the_two_new_columns_and_keeps_the_first_sighting() -> None:
    assert "excerpt" in _INSERT_COLS and "source_seen" in _INSERT_COLS
    sql = _insert_sql()
    # Existing rows win for a source that arrives again; JSONB || is right-biased.
    assert "source_seen = EXCLUDED.source_seen || events.source_seen" in sql
    values = _row_values({"subject": "s", "verdict": "OBSERVE", "sources": ["wire"]})
    seen = values[_INSERT_COLS.index("source_seen")]
    assert list(seen) == ["wire"]
    assert values[_INSERT_COLS.index("excerpt")] == ""
