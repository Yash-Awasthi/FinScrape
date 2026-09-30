"""Invalid batches must be rejected before any database work."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import require_api_key
from server.routes import events


@pytest.mark.parametrize("invalid", [{}, None, {"subject": "bad", "tickers": 7}])
def test_invalid_event_reports_422_and_index_without_ingesting(monkeypatch, invalid):
    app = FastAPI()
    app.include_router(events.router)
    app.dependency_overrides[require_api_key] = lambda: None

    def no_database():
        pytest.fail("invalid batches must not reach the database")

    monkeypatch.setattr(events.db, "pool", no_database)
    valid = {"subject": "valid", "event_type": "other", "verdict": "OBSERVE"}
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/events", json={"events": [valid, invalid]})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:3] == ["body", "events", 1]
