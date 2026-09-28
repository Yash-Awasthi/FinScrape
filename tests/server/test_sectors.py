"""/api/sectors aggregation against a fake pool.

Sector labels are free text and are normalized through `_SECTOR_ALIASES`, so two
different stored labels can land on one output sector. These pin that they combine
rather than one replacing the other.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes import data as data_routes

NOW = datetime(2026, 1, 2, tzinfo=UTC)


class FakePool:
    """Dispatches each of the four sectors queries by a phrase unique to it."""

    def __init__(self, labeled, last_rows, ticker_rows, unlabeled):
        self._by_marker = [
            ("COUNT(*) FILTER", labeled),
            ("DISTINCT ON", last_rows),
            ("t.ticker, COUNT(*)::int", ticker_rows),
            ("sector_impact IS NULL", unlabeled),
        ]

    async def fetch(self, query, *args):
        for marker, rows in self._by_marker:
            if marker in query:
                return rows
        raise AssertionError(f"unexpected query: {query}")


def _client(monkeypatch, *, labeled, last_rows, ticker_rows, unlabeled, sector_of=None):
    pool = FakePool(labeled, last_rows, ticker_rows, unlabeled)
    monkeypatch.setattr(data_routes.db, "pool", lambda: pool)
    if sector_of is not None:
        from finscrape.analysis.nlp import FinancialNLP

        monkeypatch.setattr(
            FinancialNLP, "_detect_sector", lambda self, subject, tickers: sector_of
        )
    app = FastAPI()
    app.include_router(data_routes.router)
    return TestClient(app)


def test_aliased_labels_combine_into_one_sector(monkeypatch):
    """'finance' aliases to 'financials'; both rows must add up, not overwrite."""
    labeled = [
        {
            "sector": "finance",
            "event_count": 2,
            "avg_score": 3.0,
            "bulls": 2.0,
            "bears": 0.0,
        },
        {
            "sector": "financials",
            "event_count": 3,
            "avg_score": 1.0,
            "bulls": 0.0,
            "bears": 3.0,
        },
    ]
    last_rows = [
        {
            "sector": "finance",
            "subject": "older",
            "created_at": NOW - timedelta(days=1),
        },
        {"sector": "financials", "subject": "newer", "created_at": NOW},
    ]
    ticker_rows = [
        {"sector": "finance", "ticker": "JPM", "n": 2},
        {"sector": "financials", "ticker": "JPM", "n": 3},
        {"sector": "financials", "ticker": "GS", "n": 4},
    ]
    c = _client(
        monkeypatch,
        labeled=labeled,
        last_rows=last_rows,
        ticker_rows=ticker_rows,
        unlabeled=[],
    )
    sectors = c.get("/api/sectors").json()["sectors"]
    assert [s["sector"] for s in sectors] == ["financials"]
    s = sectors[0]
    assert s["event_count"] == 5
    assert s["avg_score"] == pytest.approx((3.0 * 2 + 1.0 * 3) / 5)  # 1.8
    assert s["bull_bear_ratio"] == pytest.approx((2 + 1) / (3 + 1))  # 0.75
    assert s["top_tickers"] == ["JPM", "GS"]  # 2+3=5 beats 4
    assert s["last_event"]["subject"] == "newer"


def test_nlp_fallback_contributes_to_bull_bear_not_just_counts(monkeypatch):
    """Fallback events move the ratio too — merging only counts reported a stale one."""
    labeled = [
        {
            "sector": "energy",
            "event_count": 1,
            "avg_score": 4.0,
            "bulls": 1.0,
            "bears": 0.0,
        }
    ]
    last_rows = [{"sector": "energy", "subject": "labeled", "created_at": NOW}]
    unlabeled = [
        {
            "subject": f"crude story {i}",
            "tickers": [],
            "signal_score": -2,
            "verdict": "PULL_OUT",
            "created_at": NOW - timedelta(hours=i),
        }
        for i in range(3)
    ]
    c = _client(
        monkeypatch,
        labeled=labeled,
        last_rows=last_rows,
        ticker_rows=[],
        unlabeled=unlabeled,
        sector_of="energy",
    )
    s = c.get("/api/sectors").json()["sectors"][0]
    assert s["event_count"] == 4
    assert s["avg_score"] == pytest.approx((4.0 - 2 * 3) / 4)  # -0.5
    assert s["bull_bear_ratio"] == pytest.approx((1 + 1) / (3 + 1))  # 0.5
    assert s["last_event"]["subject"] == "labeled"  # newest of both sides
