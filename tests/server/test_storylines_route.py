"""GET /api/storylines against a fake pool.

The clusterer embeds every subject through Ollama, so it is stubbed. These pin the
two behaviours the route adds around it: the answer is reused until the event window
changes, and the clustering itself runs off the event loop (a cold embedding pass
must not stall every other request).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finscrape.analysis import clusters as clusters_mod
from server import cache
from server.routes import data as data_routes

NOW = datetime.now(UTC)


class FakePool:
    def __init__(self, rows, coverage=None):
        self._rows = rows
        self._coverage = coverage

    async def fetchrow(self, query, *args):
        assert "max(id)" in query
        return {
            "newest": max((r["id"] for r in self._rows), default=None),
            "considered": len(self._rows),
            "coverage": (
                self._coverage
                if self._coverage is not None
                else sum(
                    len(str(r["sources"])) + len(str(r["tickers"])) for r in self._rows
                )
            ),
        }

    async def fetch(self, query, *args):
        assert "ORDER BY id DESC" in query
        return list(self._rows)


def _row(event_id: int, subject: str):
    return {
        "id": event_id,
        "subject": subject,
        "tickers": ["XOM"],
        "sources": ["reuters/world"],
        "signal_score": -3,
        "created_at": NOW,
    }


@pytest.fixture()
def storylines(monkeypatch):
    calls: list[list[dict]] = []

    def _client(rows, coverage=None):
        cache.clear()
        monkeypatch.setattr(data_routes.db, "pool", lambda: FakePool(rows, coverage))

        def fake_build(events, **_kw):
            calls.append(events)
            return [
                {
                    "member_ids": [e["id"]],
                    "size": 1,
                    "tickers": ["XOM"],
                    "sources": ["reuters/world"],
                    "avg_score": -3.0,
                    "first_seen": NOW.isoformat(),
                    "top_subject": e["subject"],
                    "members": [e],
                }
                for e in events
            ]

        monkeypatch.setattr(clusters_mod, "build_storylines", fake_build)
        app = FastAPI()
        app.include_router(data_routes.router)
        return TestClient(app)

    _client.calls = calls  # type: ignore[attr-defined]
    return _client


def test_storylines_returns_clusters(storylines):
    client = storylines([_row(2, "Tanker reroutes"), _row(1, "Strait closed")])
    body = client.get("/api/storylines").json()
    assert len(body["storylines"]) == 2
    assert len(storylines.calls) == 1


def test_storylines_is_cached_until_the_window_changes(storylines):
    client = storylines([_row(2, "Tanker reroutes")])
    assert client.get("/api/storylines").status_code == 200
    assert client.get("/api/storylines").status_code == 200
    assert len(storylines.calls) == 1

    # A coverage merge changes sources/tickers without a new id; that must refresh.
    merged = storylines([_row(2, "Tanker reroutes")], coverage=999)
    assert merged.get("/api/storylines").status_code == 200
    assert len(storylines.calls) == 2


def test_storylines_applies_the_limit_after_caching(storylines):
    rows = [_row(3, "C"), _row(2, "B"), _row(1, "A")]
    client = storylines(rows)
    assert (
        len(client.get("/api/storylines", params={"limit": 1}).json()["storylines"])
        == 1
    )
    assert (
        len(client.get("/api/storylines", params={"limit": 3}).json()["storylines"])
        == 3
    )
    # Both limits share one clustering pass.
    assert len(storylines.calls) == 1


def test_storylines_handles_an_empty_database(storylines):
    client = storylines([])
    assert client.get("/api/storylines").json()["storylines"] == []
