"""DB-backed Phase 1 verify (the root-cause bug fixes), against a real Postgres.

Auto-skips when no Postgres is reachable at WORLDFIN_TEST_DATABASE_URL, so the suite stays
green without docker and this runs automatically under `make up` / CI. Tests are sync
and drive asyncpg via asyncio.run() — no pytest-asyncio needed.

Covers the Phase 1 acceptance: ingest test_event.json twice -> exactly 1 row (dedup),
and the date-count == feed-count invariant (kills the live count mismatch).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

asyncpg = pytest.importorskip("asyncpg")

from server import db, queries
from server.ingest import ingest_events
from tests.server import PG_DSN as DSN

TEST_EVENT = Path(__file__).resolve().parent / "test_event.json"


def _pg_reachable() -> bool:
    async def _check() -> bool:
        try:
            conn = await asyncio.wait_for(asyncpg.connect(DSN), timeout=2)
        except TimeoutError, OSError, asyncpg.PostgresError:
            return False
        await conn.close()
        return True

    return asyncio.run(_check())


pytestmark = pytest.mark.skipif(
    not _pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)


async def _fresh_pool() -> asyncpg.Pool:
    await db.disconnect()
    pool = await db.connect(DSN)
    await db.run_migrations(pool)
    await pool.execute("TRUNCATE events RESTART IDENTITY CASCADE")
    return pool


def test_double_ingest_dedupes_to_one_row():
    async def body():
        pool = await _fresh_pool()
        events = json.loads(TEST_EVENT.read_text())["events"]
        r1 = await ingest_events(pool, events)
        r2 = await ingest_events(pool, events)  # same payload again
        total = await pool.fetchval("SELECT COUNT(*) FROM events")
        await db.disconnect()
        assert r1["inserted"] == 1 and r1["duplicates"] == 0
        assert r2["inserted"] == 0 and r2["duplicates"] == 1
        assert total == 1  # dedup proven at the DB layer

    asyncio.run(body())


def test_date_count_matches_feed_count():
    async def body():
        pool = await _fresh_pool()
        events = json.loads(TEST_EVENT.read_text())["events"]  # timestamp 2026-05-03Z
        await ingest_events(pool, events)
        day = "2026-05-03"
        feed = await queries.get_events(pool, date=day)
        dates = {d["day"]: d["count"] for d in await queries.get_dates(pool)}
        count = await queries.count_events_for_date(pool, day)
        await db.disconnect()
        # the three views must agree — same half-open [day, day+1) bounds everywhere
        assert len(feed) == count == dates.get(day)

    asyncio.run(body())


def test_concurrent_migration_runs_do_not_collide():
    # compose starts the API while `make seed` runs; both apply migrations at once.
    async def body():
        pool = await _fresh_pool()
        await pool.execute("DELETE FROM schema_migrations")
        try:
            await asyncio.gather(db.run_migrations(pool), db.run_migrations(pool))
        finally:
            await db.run_migrations(pool)
            await db.disconnect()

    asyncio.run(body())


def test_stored_analysis_is_found_by_event_and_heuristics_are_skipped():
    # Ingest stores analysis under its own model's key; the API must still find it.
    async def body():
        pool = await _fresh_pool()
        events = json.loads(TEST_EVENT.read_text())["events"]
        eid = (await ingest_events(pool, events))["inserted_ids"][0]
        heuristic = {
            "summary": "h",
            "ticker_impacts": [{"ticker": "XOM", "reason": "heuristic"}],
        }
        flagged = {"summary": "f", "ticker_impacts": [], "heuristic": True}
        real = {"summary": "r", "ticker_impacts": [{"ticker": "XOM", "reason": "oil"}]}
        await queries.save_ai_cache(pool, "old-heuristic", eid, heuristic)
        await queries.save_ai_cache(pool, "flagged", eid, flagged)
        assert await queries.get_ai_cache_for_event(pool, eid) is None
        await queries.save_ai_cache(pool, "ingest-model", eid, real)
        found = await queries.get_ai_cache_for_event(pool, eid)
        await db.disconnect()
        assert found["summary"] == "r"

    asyncio.run(body())


def test_event_retention_deletes_old_events_and_their_outcomes():
    from worker.runner import prune_old_rows

    async def body():
        pool = await _fresh_pool()
        events = json.loads(TEST_EVENT.read_text())["events"]
        await ingest_events(pool, events)
        await pool.execute(
            "INSERT INTO accuracy_outcomes (event_id, ticker, verdict) SELECT id, 'X', 'INVEST' FROM events"
        )
        await prune_old_rows(pool, 90, 365)  # the fresh event survives
        kept = await pool.fetchval("SELECT COUNT(*) FROM events")
        await pool.execute("UPDATE events SET timestamp = now() - interval '400 days'")
        await prune_old_rows(pool, 90, 0)  # 0 keeps events forever
        forever = await pool.fetchval("SELECT COUNT(*) FROM events")
        await prune_old_rows(pool, 90, 365)
        events_left = await pool.fetchval("SELECT COUNT(*) FROM events")
        outcomes_left = await pool.fetchval("SELECT COUNT(*) FROM accuracy_outcomes")
        await db.disconnect()
        assert (kept, forever, events_left, outcomes_left) == (1, 1, 0, 0)

    asyncio.run(body())


def test_size_cap_evicts_oldest_events_instead_of_stopping():
    from worker.runner import evict_to_size

    async def body():
        pool = await _fresh_pool()
        await pool.execute(
            "INSERT INTO events (content_hash, subject, event_type, verdict, timestamp) "
            "SELECT 'h' || g, 'event ' || g, 'news', 'OBSERVE', now() - g * interval '1 day' "
            "FROM generate_series(1, 40) g"
        )
        assert await evict_to_size(pool, 100000) == 0  # under the cap: nothing leaves
        removed = await evict_to_size(
            pool, 0.001
        )  # always over: sheds oldest, then stops
        left = await pool.fetchval("SELECT count(*) FROM events")
        oldest = await pool.fetchval(
            "SELECT min(subject) FROM events WHERE subject = 'event 40'"
        )
        await db.disconnect()
        assert 0 < removed < 40 and left == 40 - removed
        assert oldest is None  # the oldest event went first

    asyncio.run(body())


def test_same_story_from_three_sources_merges_into_one_row():
    """plan M1.5: RSS, GDELT and a blocked-feed fallback carry the same story with
    three different links. That is one row, with the union of sources and articles."""

    async def body():
        pool = await _fresh_pool()
        story = {
            "subject": "Hormuz shipping halts",
            "event_type": "geopolitical",
            "verdict": "INVEST",
            "signal_score": 3,
            "confidence": 0.7,
            "timestamp": "2026-05-03T09:00:00Z",
        }
        rss = {
            **story,
            "sources": ["world/reuters"],
            "articles": ["https://reuters.com/a?utm_source=rss"],
        }
        gdelt = {
            **story,
            "sources": ["gdelt"],
            "articles": ["https://gdelt.example.com/summary?id=9"],
        }
        fallback = {
            **story,
            "sources": ["world/aljazeera"],
            "articles": ["https://aljazeera.example.com/oil/1"],
        }
        first = await ingest_events(pool, [rss])
        second = await ingest_events(pool, [gdelt])
        third = await ingest_events(pool, [fallback])
        total = await pool.fetchval("SELECT COUNT(*) FROM events")
        row = await pool.fetchrow("SELECT sources, articles FROM events")
        await db.disconnect()
        assert (first["inserted"], first["merged"]) == (1, 0)
        assert (second["inserted"], second["merged"]) == (0, 1)
        assert (third["inserted"], third["merged"]) == (0, 1)
        assert (second["duplicates"], third["duplicates"]) == (1, 1)
        assert total == 1  # one story, one row
        assert row["sources"] == ["gdelt", "world/aljazeera", "world/reuters"]
        assert len(row["articles"]) == 3

    asyncio.run(body())


def test_source_health_flips_at_the_configured_window_and_ignores_feed_timestamps():
    """plan M1.5: STALE comes from when WE fetched, never from how old the feed's own
    items are — a healthy source that re-serves a three-day-old story is not stale."""
    from worker.health import aggregate_health

    async def body():
        pool = await _fresh_pool()
        await pool.execute("TRUNCATE source_health")
        # Healthy, fetched just now, but its newest item is three days old.
        await pool.execute(
            "INSERT INTO source_health (source, fetched_at, record_count, status) "
            "VALUES ('world/old_but_healthy', now(), 1, 'OK')"
        )
        await pool.execute(
            "INSERT INTO events (content_hash, subject, event_type, verdict, timestamp) "
            "VALUES ('h', 'three days old', 'news', 'OBSERVE', now() - interval '3 days')"
        )
        fresh = {r["source"]: r["status"] for r in await aggregate_health(pool, 60)}
        # One second past the window reads STALE; one second inside it does not.
        await pool.execute(
            "UPDATE source_health SET fetched_at = now() - interval '59 minutes' "
            "WHERE source = 'world/old_but_healthy'"
        )
        inside = {r["source"]: r["status"] for r in await aggregate_health(pool, 60)}
        await pool.execute(
            "UPDATE source_health SET fetched_at = now() - interval '61 minutes' "
            "WHERE source = 'world/old_but_healthy'"
        )
        outside = {r["source"]: r["status"] for r in await aggregate_health(pool, 60)}
        # The window is the setting, not a constant.
        wide = {r["source"]: r["status"] for r in await aggregate_health(pool, 120)}
        await db.disconnect()
        assert fresh["world/old_but_healthy"] == "OK"
        assert inside["world/old_but_healthy"] == "OK"
        assert outside["world/old_but_healthy"] == "STALE"
        assert wide["world/old_but_healthy"] == "OK"

    asyncio.run(body())


def test_retention_keeps_the_documented_window_and_deletes_just_past_it():
    """plan M1.5: the sweep deletes events past the documented window and nothing
    newer — an event one day inside the window must survive its own sweep."""
    from worker.runner import prune_old_rows

    async def body():
        pool = await _fresh_pool()
        await pool.execute(
            "INSERT INTO events (content_hash, subject, event_type, verdict, timestamp) VALUES "
            "('inside', 'just inside', 'news', 'OBSERVE', now() - interval '364 days'), "
            "('edge', 'at the edge', 'news', 'OBSERVE', now() - interval '365 days' + interval '1 hour'), "
            "('past', 'just past', 'news', 'OBSERVE', now() - interval '365 days' - interval '1 hour')"
        )
        await pool.execute(
            "INSERT INTO accuracy_outcomes (event_id, ticker, verdict) "
            "SELECT id, 'X', 'INVEST' FROM events WHERE content_hash = 'past'"
        )
        await prune_old_rows(pool, 90, 365)
        left = await pool.fetch("SELECT content_hash FROM events ORDER BY content_hash")
        orphans = await pool.fetchval(
            "SELECT count(*) FROM accuracy_outcomes o LEFT JOIN events e ON e.id = o.event_id "
            "WHERE e.id IS NULL"
        )
        await db.disconnect()
        assert [r["content_hash"] for r in left] == ["edge", "inside"]
        assert orphans == 0  # the deleted event took its scored row with it

    asyncio.run(body())
