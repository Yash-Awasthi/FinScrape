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

TEST_EVENT = Path(__file__).resolve().parents[2] / "test_event.json"


def _pg_reachable() -> bool:
    async def _check() -> bool:
        try:
            conn = await asyncio.wait_for(asyncpg.connect(DSN), timeout=2)
        except (TimeoutError, OSError, asyncpg.PostgresError):
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
