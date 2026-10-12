"""/api/accuracy and /api/outcomes against a fake pool."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes import accuracy

T1 = datetime(2026, 10, 1, tzinfo=UTC)
T2 = datetime(2026, 10, 2, tzinfo=UTC)
ROWS = [
    {
        "event_id": 2,
        "subject": "Later call",
        "verdict": "PULL_OUT",
        "tickers": ["XOM"],
        "timestamp": T2,
        "price_move_pct": -1.5,
        "correct": False,
        "correct2": None,
        "correct4": None,
        "ex2": None,
        "ex4": None,
        "confidence": 0.6,
    },
    {
        "event_id": 1,
        "subject": "Earlier call",
        "verdict": "INVEST",
        "tickers": ["AAPL"],
        "timestamp": T1,
        "price_move_pct": 2.0,
        "correct": True,
        "correct2": True,
        "correct4": None,
        "ex2": 0.8,
        "ex4": None,
        "confidence": 0.7,
    },
]


@pytest.fixture()
def client(monkeypatch):
    calls: list = []

    class Pool:
        async def fetch(self, sql, *args):
            calls.append(args)
            if args and args[0] is not None:
                return [r for r in ROWS if r["event_id"] == args[0]]
            return ROWS

    monkeypatch.setattr(accuracy.db, "pool", lambda: Pool())
    app = FastAPI()
    app.include_router(accuracy.router)
    return TestClient(app), calls


def test_outcomes_lists_each_scored_call(client):
    c, _ = client
    body = c.get("/api/outcomes").json()["outcomes"]
    assert [o["subject"] for o in body] == ["Later call", "Earlier call"]
    assert body[1]["correct2"] is True and body[0]["timestamp"].startswith("2026-10-02")


def test_outcomes_filters_by_event(client):
    c, calls = client
    body = c.get("/api/outcomes?event_id=1").json()["outcomes"]
    assert [o["event_id"] for o in body] == [1] and calls[-1][0] == 1


def test_accuracy_curve_runs_in_event_time(client):
    c, _ = client
    body = c.get("/api/accuracy").json()
    assert body["equity_curve"] == [1, 0]
    assert body["vs_spy"]["d2"]["hits"] == 1
