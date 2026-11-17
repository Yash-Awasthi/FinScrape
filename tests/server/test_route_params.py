"""Boundary validation on the read routes.

A malformed filter is a client error, not a 500: `date.fromisoformat` used to be
reached straight from the query string, and yfinance took any symbol string.
These mount the real routers on a throwaway app — every case below fails before a
database or network call, so no Postgres is needed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes import correlations as correlations_routes
from server.routes import events as events_routes
from server.routes import market as market_routes


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(events_routes.router)
    app.include_router(correlations_routes.router)
    app.include_router(market_routes.router)
    return TestClient(app)


@pytest.mark.parametrize("bad", ["garbage", "2026-13-01", "2026-02-30", "10/22/2026"])
def test_events_rejects_a_bad_date_with_422(client, bad):
    response = client.get("/api/events", params={"date": bad})
    assert response.status_code == 422
    assert "date" in response.json()["detail"]


@pytest.mark.parametrize("bad", ["garbage", "2026-00-10"])
def test_correlations_rejects_a_bad_date_with_422(client, bad):
    response = client.get("/api/correlations", params={"date": bad})
    assert response.status_code == 422


@pytest.mark.parametrize("limit", [0, -1, 501])
def test_correlations_bounds_its_limit(client, limit):
    response = client.get("/api/correlations", params={"limit": limit})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "bad", ["../../etc/passwd", "A" * 40, "XOM;DROP", "", "<script>"]
)
def test_candles_rejects_a_non_symbol(client, bad):
    response = client.get("/api/candles", params={"symbol": bad})
    assert response.status_code == 422
