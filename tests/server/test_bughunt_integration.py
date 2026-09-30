"""Real SQL coverage for same-cycle dedup and scenario evidence refresh."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from finscrape.analysis import embeddings
from server import cache, db
from server.ingest import ingest_events
from server.routes.insight import scenarios
from tests.server import fresh_pool, pg_reachable
from worker.runner import merge_coverage, unvisited

pytestmark = pytest.mark.skipif(not pg_reachable(), reason="isolated Postgres required")


def test_unvisited_dedupes_canonical_urls_inside_one_fetch():
    async def check():
        pool = await fresh_pool("visited_urls")
        urls = [
            "https://example.com/story?utm_source=a",
            "https://example.com/story",
            "ingestor://usgs",
            "ingestor://usgs",
            "https://example.com/other",
        ]
        items = [(SimpleNamespace(url=url), None) for url in urls]
        try:
            result = await unvisited(pool, items)
            assert [a.url for a, _ in result] == [urls[0], *urls[2:]]
        finally:
            await db.disconnect()

    asyncio.run(check())


def test_scenarios_refresh_after_coverage_merges_without_new_event(monkeypatch):
    monkeypatch.setattr(embeddings, "embed", lambda _text: None)

    async def check():
        cache.clear()
        pool = await fresh_pool("events")
        event = {
            "subject": "Strait closed",
            "verdict": "INVEST",
            "signal_score": 4,
            "confidence": 0.9,
            "articles": ["https://example.com/one"],
            "sources": ["world/one:wire"],
            "tickers": ["XOM"],
            "timestamp": datetime.now(UTC).isoformat(),
        }
        try:
            await ingest_events(pool, [event])
            first = await scenarios(limit=6, window=200)
            assert first["scenarios"][0]["reports"] == 1
            await merge_coverage(
                pool, [(event["subject"], "https://example.com/two", "world/two:wire")]
            )
            result = await scenarios(limit=6, window=200)
            assert result["events_considered"] == 1
            assert result["scenarios"][0]["reports"] == 2
        finally:
            cache.clear()
            await db.disconnect()

    asyncio.run(check())
