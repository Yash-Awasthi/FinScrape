"""Phase 4 DB integration: correlation persistence + query (skip-ready).

Auto-skips without Postgres; runs under `make up` / CI. Three corroborating sources on
one story → convergence + triangulation signals → persisted → queryable by day.
"""

from __future__ import annotations

import asyncio

import pytest

asyncpg = pytest.importorskip("asyncpg")

from server.correlate import NewsItem, analyze_correlations
from tests.server import fresh_pool, pg_reachable

pytestmark = pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)


def test_persist_and_query_correlations():
    from server import db
    from worker.runner import persist_correlations

    async def body():
        pool = await fresh_pool("correlations")
        title = "Oil pipeline supply halt in the strait"
        base = 1_700_000_000.0
        items = [
            NewsItem(title, title, "w", "wire", timestamp=base),
            NewsItem(title, title, "g", "gov", timestamp=base - 10),
            NewsItem(title, title, "i", "intel", timestamp=base - 20),
        ]
        signals, _ = analyze_correlations(items, prev_snapshot={"topics": {}})
        assert {s.type for s in signals} >= {"convergence", "triangulation"}

        await persist_correlations(pool, signals)

        count = await pool.fetchval("SELECT COUNT(*) FROM correlations")
        assert count == len(signals)
        types = {
            r["signal_type"]
            for r in await pool.fetch("SELECT signal_type FROM correlations")
        }
        assert "triangulation" in types and "convergence" in types
        await db.disconnect()

    asyncio.run(body())
