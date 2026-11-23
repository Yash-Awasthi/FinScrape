"""Filtered feed reads stay index-backed, and the published plans stay honest (plan M3.2).

Two halves: the offline half checks `docs/QUERIES.md` names every query this repository
knows about (so the document cannot rot silently); the DB half seeds enough rows for the
planner to care and fails if a filtered feed read falls back to a sequential scan.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

asyncpg = pytest.importorskip("asyncpg")

from scripts.explain import QUERIES, explain_all
from tests.server import PG_DSN as DSN

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "QUERIES.md"


def _pg_reachable() -> bool:
    async def _check() -> bool:
        try:
            conn = await asyncio.wait_for(asyncpg.connect(DSN), timeout=2)
        except TimeoutError, OSError, asyncpg.PostgresError:
            return False
        await conn.close()
        return True

    return asyncio.run(_check())


def test_the_document_names_every_query() -> None:
    assert DOC.exists(), "run `make explain` to publish the plans"
    text = DOC.read_text(encoding="utf-8")
    for query in QUERIES:
        assert f"`{query.key}`" in text, query.key
    # The plan names columns the table does not have; the mapping must be stated or the
    # document reads as if published_at/topic/ticker were real columns.
    assert "published_at" in text and "tickers" in text


@pytest.mark.skipif(
    not _pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)
def test_every_filtered_feed_read_uses_an_index() -> None:
    results = asyncio.run(explain_all(DSN, seed_rows=5000))

    def cleanup() -> None:
        async def _drop() -> None:
            conn = await asyncpg.connect(DSN)
            try:
                await conn.execute(
                    "DELETE FROM events WHERE content_hash LIKE 'explain-%'"
                )
            finally:
                await conn.close()

        asyncio.run(_drop())

    try:
        filtered = {k: v for k, v in results.items() if v["filtered"]}
        assert filtered, "the filtered read set is empty"
        for key, result in filtered.items():
            assert not result["seq_scan_events"], (
                f"{key} seq-scans events: {result['plan']}"
            )
            assert result["indexes"], f"{key} has no index in its plan"
        # The aggregate is allowed to scan; asserting it does *not* would be a false gate.
        assert results["stats"]["filtered"] is False
    finally:
        cleanup()
