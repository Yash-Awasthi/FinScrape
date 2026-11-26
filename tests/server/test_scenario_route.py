"""One scenario by id (plan m4.2.2): members, probability interval, history and window.

The list builder is stubbed, so this pins the route's assembly, its 404 and the
what-if recompute, not the clustering engine (tests/test_scenarios.py covers that).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes import insight

SCENARIO = {
    "id": "s7",
    "title": "Tankers stop",
    "probability": 0.74,
    "ci95": [0.6, 0.88],
    "n_members": 2,
    "member_ids": [7, 8],
    "sectors": [{"name": "energy", "direction": "down", "strength": 1.0, "tilt": -0.4}],
    "exposure": [{"name": "XOM", "direction": "down", "strength": 1.0, "tilt": -0.3}],
}

MEMBER = {
    "id": 7,
    "subject": "Tankers stop",
    "verdict": "PULL_OUT",
    "signal_score": -4,
    "confidence": 0.8,
    "sector_impact": "energy",
    "timestamp": None,
    "sources": ["reuters/world"],
}

# The columns the scenario engine grades on; the what-if rebuild reads these.
WIDE = {
    "subject": "Tankers stop",
    "reasoning": "",
    "verdict": "PULL_OUT",
    "signal_score": -4,
    "confidence": 0.8,
    "event_type": "supply",
    "magnitude": "high",
    "actionability": "high",
    "sector_impact": "energy",
    "divergence_flag": False,
    "tickers": ["XOM"],
    "sources": ["reuters/world"],
    "articles": ["https://example.test/a"],
    "affected_entities": [],
    "second_order_effects": [],
    "created_at": None,
}


class FakePool:
    def __init__(self):
        self.statements = []

    async def fetch(self, sql, *args):
        self.statements.append((sql, args))
        if "scenario_history" in sql:
            assert args == ("s7",)
            import datetime as dt

            base = dt.datetime(2026, 5, 3, 8, 0, tzinfo=dt.UTC)
            return [
                {
                    "probability": 0.8,
                    "n_members": 2,
                    "computed_at": base + dt.timedelta(hours=2),
                },
                {"probability": 0.61, "n_members": 2, "computed_at": base},
            ]
        if "accuracy_outcomes" in sql:
            return []
        if "FROM events WHERE id = ANY" in sql:
            wanted = [int(i) for i in args[0]]
            return [{**MEMBER, "id": i} for i in wanted]
        # The wide scenario query the what-if rebuild shares with /api/scenarios.
        assert args == (200,)
        return [
            {**WIDE, "id": 7},
            {**WIDE, "id": 8, "subject": "Second tanker stops"},
        ]


def _client(monkeypatch, scenario=SCENARIO):
    async def _fake_scenarios(limit=6, window=200):
        return {"scenarios": [scenario], "events_considered": 42}

    app = FastAPI()
    app.include_router(insight.router)
    monkeypatch.setattr(insight, "scenarios", _fake_scenarios)
    monkeypatch.setattr(insight.db, "pool", lambda: FakePool())
    return TestClient(app)


def test_one_scenario_carries_its_members_probability_history_and_window(
    monkeypatch,
) -> None:
    body = _client(monkeypatch).get("/api/scenarios/s7").json()
    assert body["scenario"]["probability"] == 0.74
    assert body["scenario"]["ci95"] == [0.6, 0.88]
    assert [m["id"] for m in body["members"]] == [7, 8]
    # Oldest first: a sparkline reads left to right in time.
    assert [h["probability"] for h in body["history"]] == [0.61, 0.8]
    assert body["history"][1]["at"] == "2026-05-03T10:00:00+00:00"
    assert body["window"] == {
        "events_considered": 42,
        "event_cap": 200,
        "lookback_days": 14,
    }
    assert body["what_if"] is None


def test_a_stale_scenario_id_is_a_404(monkeypatch) -> None:
    response = _client(monkeypatch).get("/api/scenarios/s999")
    assert response.status_code == 404
    assert response.json()["detail"] == "scenario not found"


def test_exclude_drops_one_member_and_reports_the_recomputed_probability(
    monkeypatch,
) -> None:
    body = _client(monkeypatch).get("/api/scenarios/s7?exclude=7").json()
    what_if = body["what_if"]
    assert what_if["excluded_id"] == 7
    assert what_if["label"] == "hypothetical: this member removed"
    assert what_if["n_members"] == 1
    # Only event 8 is left and it carries no spread, so the interval is null.
    assert what_if["ci95"] is None
    # One member means its own analyzed score decides: 0.5 + 0.08 * -4 = 0.18.
    assert what_if["probability"] == 0.82
    # The stored scenario and its members are untouched.
    assert body["scenario"]["probability"] == 0.74
    assert [m["id"] for m in body["members"]] == [7, 8]


def test_exclude_that_is_not_a_member_is_a_400(monkeypatch) -> None:
    response = _client(monkeypatch).get("/api/scenarios/s7?exclude=99")
    assert response.status_code == 400
    assert response.json()["detail"] == "exclude 99 is not a member of this scenario"


def test_a_one_member_scenario_cannot_lose_its_member(monkeypatch) -> None:
    single = {**SCENARIO, "n_members": 1, "member_ids": [7]}
    response = _client(monkeypatch, single).get("/api/scenarios/s7?exclude=7")
    assert response.status_code == 400
    assert (
        response.json()["detail"] == "a scenario with one member cannot lose a member"
    )


def test_history_keeps_moves_and_hourly_points_not_every_page_reload() -> None:
    assert insight.should_record(None, 0.7, None) is True
    assert insight.should_record(0.7, 0.7, 30) is False
    assert insight.should_record(0.7, 0.702, 30) is False
    assert insight.should_record(0.7, 0.71, 30) is True
    assert insight.should_record(0.7, 0.7, 4000) is True
