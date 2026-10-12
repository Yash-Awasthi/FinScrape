"""Migration 0013 against a real Postgres: score-0 rows relabel, social_posts is gone."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

asyncpg = pytest.importorskip("asyncpg")

from server import db
from tests.server import PG_DSN, pg_reachable

pytestmark = pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)

SQL = (
    Path(__file__).resolve().parents[2]
    / "server/migrations/0013_relabel_neutral_drop_social.sql"
).read_text()


def test_score_zero_reads_observe_and_social_posts_is_gone():
    async def body():
        await db.disconnect()
        pool = await db.connect(PG_DSN)
        await db.run_migrations(pool)
        await pool.execute("TRUNCATE events RESTART IDENTITY CASCADE")
        for h, score, verdict in (
            ("a", 0, "CAUTIOUS"),
            ("b", -1, "CAUTIOUS"),
            ("c", 0, "OBSERVE"),
        ):
            await pool.execute(
                "INSERT INTO events (content_hash, subject, signal_score, verdict) "
                "VALUES ($1, $1, $2, $3)",
                h,
                score,
                verdict,
            )
        await pool.execute(SQL)  # rerunning is safe: the update and drop are idempotent
        rows = {
            r["content_hash"]: r["verdict"]
            for r in await pool.fetch("SELECT content_hash, verdict FROM events")
        }
        gone = await pool.fetchval("SELECT to_regclass('social_posts') IS NULL")
        await db.disconnect()
        return rows, gone

    rows, gone = asyncio.run(body())
    assert rows == {"a": "OBSERVE", "b": "CAUTIOUS", "c": "OBSERVE"}
    assert gone
