"""Production insight routes (predict/reliability) against a fake Postgres pool."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes import insight


def _selected_columns(query: str) -> set[str]:
    """Column names between SELECT and FROM, stripped of table prefixes and aliases."""
    body = re.split(r"\bFROM\b", query, flags=re.IGNORECASE)[0]
    body = re.sub(r"^\s*SELECT\s+", "", body, flags=re.IGNORECASE)
    names = set()
    for part in body.split(","):
        token = part.strip().split()[-1] if part.strip() else ""
        if token:
            names.add(token.rsplit(".", 1)[-1].lower())
    return names


class FakeRow(dict):
    """asyncpg Record stand-in: reading a column the query did not select is a KeyError."""

    def __getitem__(self, key):
        return dict.__getitem__(self, key)


class FakePool:
    def __init__(self, rows: list[dict], outcome_rows: list[dict]):
        self._rows = rows
        self._outcomes = outcome_rows

    @staticmethod
    def _project(row: dict, query: str) -> FakeRow:
        """Only the selected columns come back — a Record has no others to read."""
        cols = _selected_columns(query)
        return FakeRow({k: v for k, v in row.items() if k.lower() in cols})

    async def fetchrow(self, query, *args):
        for row in self._rows:
            if row["id"] == args[0]:
                return self._project(row, query)
        return None

    async def fetch(self, query, *args):
        return [self._project(r, query) for r in self._outcomes]


@pytest.fixture()
def client(monkeypatch):
    now = datetime.now(UTC)
    event_rows = [
        {
            "id": 7,
            "subject": "nvda earnings beat",
            "verdict": "INVEST",
            "signal_score": 4,
            "confidence": 0.8,
            "event_type": "earnings",
            "sources": json.dumps(["cnbc", "rss"]),
            "tickers": json.dumps(["NVDA"]),
            "reasoning": "strong data center demand",
        }
    ]
    outcome_rows = [
        {
            "verdict": "INVEST",
            "correct": True,
            "checked_at": now,
            "confidence": 0.8,
            "event_type": "earnings",
            "sources": json.dumps(["cnbc"]),
        },
        {
            "verdict": "INVEST",
            "correct": True,
            "checked_at": now,
            "confidence": 0.7,
            "event_type": "earnings",
            "sources": json.dumps(["rss"]),
        },
    ]
    fake = FakePool(event_rows, outcome_rows)
    monkeypatch.setattr(insight.db, "pool", lambda: fake)

    app = FastAPI()
    app.include_router(insight.router)
    return TestClient(app)


def test_reliability_from_outcomes(client):
    body = client.get("/api/reliability").json()
    rel = body["reliability"]
    assert rel["sample_size"] == 2
    assert rel["by_verdict"]["INVEST"]["hit_rate"] == 1.0
    assert rel["by_source"]["cnbc"]["hit_rate"] == 1.0


def test_predict_event_attaches_evidence(client):
    body = client.get("/api/predict/7").json()
    assert body["event"]["id"] == 7
    assert body["event"]["ticker"] == "NVDA"
    assert 0 <= body["p_verdict_correct"] <= 1
    assert body["data_tier"] in ("empirical", "thin-data")
    # INVEST on 2-for-2 outcomes should lean positive
    assert body["p_verdict_correct"] >= 0.5


def test_predict_unknown_event_404(client):
    assert client.get("/api/predict/9999").status_code == 404
