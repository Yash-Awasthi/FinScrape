"""The digest reads its window of events from Postgres; needs a test DB."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("asyncpg")

from tests.server import fresh_pool, pg_reachable

pytestmark = pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)


def test_recent_events_keeps_only_the_window():
    from server import db
    from worker.digest import recent_events

    async def body():
        pool = await fresh_pool("events")
        for subject, hours in (("fresh", 2), ("stale", 72)):
            await pool.execute(
                "INSERT INTO events (content_hash, subject, event_type, verdict, tickers, timestamp) "
                "VALUES ($1, $1, 'other', 'INVEST', '[\"XOM\"]', now() - make_interval(hours => $2))",
                subject,
                hours,
            )
        daily = await recent_events(pool, 24)
        assert [e["subject"] for e in daily] == ["fresh"]
        assert daily[0]["tickers"] == ["XOM"]
        assert len(await recent_events(pool, 24 * 7)) == 2
        await db.disconnect()

    asyncio.run(body())
