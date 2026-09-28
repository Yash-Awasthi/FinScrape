"""GET /api/scenarios against a fake Postgres pool.

Clustering is stubbed: `build_storylines` would embed every subject through
Ollama, which is neither available nor the thing under test here. The stub also
pins the contract the route depends on — clusters carrying full member dicts.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finscrape.analysis import clusters as clusters_mod
from server import cache
from server.routes import insight

NOW = datetime.now(UTC)


def _event_row(event_id: int, subject: str, **overrides):
    row = {
        "id": event_id,
        "subject": subject,
        "reasoning": "tanker traffic halted",
        "verdict": "PULL_OUT",
        "signal_score": -4,
        "confidence": 0.8,
        "event_type": "geopolitical",
        "magnitude": "high",
        "actionability": "high",
        "sector_impact": "energy/transport",
        "divergence_flag": False,
        "tickers": json.dumps(["XOM"]),
        "sources": json.dumps(["reuters/world"]),
        "articles": json.dumps(["https://reuters/1", "https://ap/1"]),
        "affected_entities": json.dumps([{"name": "Shell", "ticker": "SHEL"}]),
        "second_order_effects": json.dumps(["Freight rates spike"]),
        "created_at": NOW,
    }
    row.update(overrides)
    return row


OUTCOME_ROWS = [
    {
        "verdict": "PULL_OUT",
        "correct": True,
        "checked_at": NOW,
        "confidence": 0.8,
        "event_type": "geopolitical",
        "sources": json.dumps(["reuters"]),
    }
]


class FakePool:
    """Dispatches on the query: the route reads events and outcomes separately."""

    def __init__(self, event_rows):
        self._events = event_rows

    async def fetch(self, query, *args):
        if re.search(r"accuracy_outcomes", query, re.IGNORECASE):
            return list(OUTCOME_ROWS)
        limit = args[0] if args else len(self._events)
        return list(self._events)[:limit]

    async def fetchrow(self, query, *args):
        """The route settles the cache key from this before fetching anything."""
        window = args[0] if args else len(self._events)
        rows = list(self._events)[:window]
        return {
            "newest": max((r["id"] for r in rows), default=None),
            "considered": len(rows),
        }


@pytest.fixture()
def make_client(monkeypatch):
    def _make(event_rows):
        cache.clear()  # keys survive between tests otherwise
        monkeypatch.setattr(insight.db, "pool", lambda: FakePool(event_rows))
        monkeypatch.setattr(
            clusters_mod,
            "build_storylines",
            lambda events, **_kw: (
                [
                    {
                        "members": list(events),
                        "top_subject": events[0]["subject"] if events else "",
                        "sources": ["reuters/world"],
                        "first_seen": NOW.isoformat(),
                        "size": len(events),
                    }
                ]
                if events
                else []
            ),
        )
        app = FastAPI()
        app.include_router(insight.router)
        return TestClient(app)

    return _make


def test_scenarios_carry_advice_exposure_and_a_probability(make_client):
    client = make_client(
        [
            _event_row(2, "Strait closed to tankers"),
            _event_row(1, "Second carrier reroutes"),
        ]
    )
    body = client.get("/api/scenarios").json()

    assert body["events_considered"] == 2
    scenario = body["scenarios"][0]
    assert scenario["size"] == 2
    assert scenario["id"] == "s1"  # lowest member id, stable across orderings
    assert 0.5 <= scenario["probability"] <= 1.0
    assert scenario["stance"] in ("risk-on", "risk-off", "mixed")
    assert scenario["advice"]
    assert {leg["name"] for leg in scenario["exposure"]} >= {"XOM", "SHEL"}
    assert scenario["chain"] == ["Freight rates spike"]


def test_jsonb_columns_survive_both_driver_shapes(make_client):
    """asyncpg returns JSONB as a str on some drivers and as the value on others."""
    client = make_client(
        [
            _event_row(2, "Strait closed", tickers=["XOM"], second_order_effects=["A"]),
            _event_row(1, "Reroute", tickers=json.dumps(["XOM"])),
        ]
    )
    exposure = client.get("/api/scenarios").json()["scenarios"][0]["exposure"]
    assert "XOM" in {leg["name"] for leg in exposure}


def test_malformed_jsonb_degrades_instead_of_500ing(make_client):
    client = make_client([_event_row(1, "Strait closed", tickers="{not json")])
    body = client.get("/api/scenarios").json()
    assert body["scenarios"][0]["exposure"]  # entity ticker still carries it


def test_no_events_is_an_empty_answer_not_an_error(make_client):
    client = make_client([])
    body = client.get("/api/scenarios").json()
    assert body == {"scenarios": [], "events_considered": 0}


def test_limit_is_bounded(make_client):
    client = make_client([_event_row(1, "Strait closed")])
    assert client.get("/api/scenarios?limit=0").status_code == 422
    assert client.get("/api/scenarios?limit=99").status_code == 422


def test_startup_warm_up_fills_the_cache(make_client, caplog):
    """The warm-up calls the route as a plain function, where Query() defaults are
    objects rather than numbers."""
    import asyncio
    import logging

    from server.app import _warm_scenarios
    from server.settings import Settings

    make_client([_event_row(1, "Strait closed")])
    with caplog.at_level(logging.INFO):
        asyncio.run(_warm_scenarios(Settings(_env_file=None)))
    assert "scenario cache warmed" in caplog.text
