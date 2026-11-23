"""The poll asks for the delta, not the whole feed (plan M3.3).

`GET /api/events?since_id=N` must return only rows newer than N, newest-first, and every
other filter must keep working alongside it. The dashboard relies on this to avoid
re-downloading 200 unchanged events every 60 s.
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


def _row(n: int) -> dict:
    base = json.loads(TEST_EVENT.read_text())["events"][0]
    return {
        **base,
        "subject": f"Poll delta {n}",
        "content_hash": f"since-{n}",
        "timestamp": f"2026-05-03T0{n}:00:00Z",
        "sources": [f"world/test-{n}"],
    }


def test_since_id_returns_only_newer_rows_newest_first():
    async def body():
        await db.disconnect()
        pool = await db.connect(DSN)
        await db.run_migrations(pool)
        await pool.execute("TRUNCATE events RESTART IDENTITY CASCADE")
        ids = (await ingest_events(pool, [_row(n) for n in (1, 2, 3)]))["inserted_ids"]
        everything = await queries.get_events(pool, limit=50)
        delta = await queries.get_events(pool, since_id=ids[0], limit=50)
        filtered = await queries.get_events(pool, since_id=ids[0], verdict="INVEST")
        await db.disconnect()
        assert [e["id"] for e in everything] == sorted(ids, reverse=True)
        assert [e["id"] for e in delta] == [ids[2], ids[1]]
        # The delta composes with the other filters instead of overriding them.
        assert [e["id"] for e in filtered] == [ids[2], ids[1]]

    asyncio.run(body())


def test_since_id_past_the_newest_row_is_empty():
    async def body():
        await db.disconnect()
        pool = await db.connect(DSN)
        await db.run_migrations(pool)
        await pool.execute("TRUNCATE events RESTART IDENTITY CASCADE")
        ids = (await ingest_events(pool, [_row(1)]))["inserted_ids"]
        delta = await queries.get_events(pool, since_id=ids[-1], limit=50)
        await db.disconnect()
        # The steady state: nothing new, so the poll returns an empty body, not a replay.
        assert delta == []

    asyncio.run(body())
