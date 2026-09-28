"""Phase 3 DB integration: source_health + scrape_runs round-trip (skip-ready).

Auto-skips without Postgres; runs under `make up` / CI. Verifies the freshness model:
a healthy source reads OK, then reads STALE once its fetch ages past the window.
"""

from __future__ import annotations

import asyncio

import pytest

asyncpg = pytest.importorskip("asyncpg")

from tests.server import fresh_pool, pg_reachable

pytestmark = pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)


def test_source_health_ok_then_stale():
    from server import db
    from worker.health import aggregate_health, record_source_health

    async def body():
        pool = await fresh_pool("source_health")
        await record_source_health(pool, "world_rss", 7, "OK")

        rows = {
            r["source"]: r for r in await aggregate_health(pool, stale_after_min=60)
        }
        assert rows["world_rss"]["status"] == "OK"
        assert rows["world_rss"]["record_count"] == 7

        # age the fetch beyond the window → derived STALE (no writer touched it)
        await pool.execute(
            "UPDATE source_health SET fetched_at = now() - interval '2 hours' WHERE source = 'world_rss'"
        )
        rows = {
            r["source"]: r for r in await aggregate_health(pool, stale_after_min=60)
        }
        assert rows["world_rss"]["status"] == "STALE"
        await db.disconnect()

    asyncio.run(body())


def test_scrape_run_lifecycle():
    from server import db
    from worker.health import finish_scrape_run, start_scrape_run

    async def body():
        pool = await fresh_pool("scrape_runs")
        run_id = await start_scrape_run(pool, "gdelt")
        assert run_id is not None
        await finish_scrape_run(pool, run_id, "ok", 3)
        row = await pool.fetchrow(
            "SELECT status, events_ingested FROM scrape_runs WHERE id = $1", run_id
        )
        assert row["status"] == "ok" and row["events_ingested"] == 3
        await db.disconnect()

    asyncio.run(body())


def test_feed_health_rows_per_feed():
    from server import db
    from worker.health import aggregate_health, record_feed_health

    async def body():
        pool = await fresh_pool("source_health")
        await record_feed_health(pool, {"bbc": (4, None), "gone": (0, "fetch failed")})
        # a feed dropped from the registry must not linger as a STALE row
        await record_feed_health(pool, {"bbc": (3, None), "dw": (0, "fetch failed")})
        rows = {r["source"]: r for r in await aggregate_health(pool, 60)}
        assert rows.keys() == {"world/bbc", "world/dw"}
        assert rows["world/bbc"]["status"] == "OK"
        assert rows["world/bbc"]["record_count"] == 3
        assert rows["world/dw"]["status"] == "WARN"
        await db.disconnect()

    asyncio.run(body())


def test_paraphrased_report_merges_into_the_postgres_row(monkeypatch):
    """Dedup reads Postgres, so a second outlet's paraphrase lands on the stored row."""
    import finscrape.pipeline as pipeline_mod
    from finscrape.models import FinEvent
    from finscrape.pipeline import FinScrapePipeline
    from server import db
    from server.ingest import ingest_events
    from worker.runner import PostgresEvents, merge_coverage

    # Paraphrase detection is Ollama's job; stand in for it with the best candidate.
    monkeypatch.setattr(
        pipeline_mod, "most_similar", lambda text, cands, threshold: (cands[0][0], 0.7)
    )

    def event(subject: str, url: str, source: str) -> FinEvent:
        return FinEvent(
            subject=subject,
            event_type="geopolitical_event",
            tickers=["XOM", "CVX"],
            impact_direction="negative",
            signal_score=-3,
            confidence=0.7,
            verdict="PULL_OUT",
            sources=[source],
            articles=[url],
        )

    async def body():
        pool = await fresh_pool("events")
        first = event(
            "iran closes strait of hormuz", "https://bbc.example/a", "world/bbc"
        )
        await ingest_events(pool, [first.to_dict()])

        pipeline = FinScrapePipeline(PostgresEvents(pool))
        second = event(
            "tehran shuts hormuz to tankers", "https://dw.example/b", "world/dw"
        )
        matched = await asyncio.to_thread(pipeline._find_duplicate, second)
        assert matched is not None and matched["subject"] == first.subject

        await merge_coverage(
            pool, [(matched["subject"], "https://dw.example/b", "world/dw")]
        )
        row = await pool.fetchrow("SELECT articles, sources FROM events")
        assert "https://dw.example/b" in row["articles"]
        assert "world/dw" in row["sources"]
        await db.disconnect()

    asyncio.run(body())
