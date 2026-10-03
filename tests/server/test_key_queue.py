"""The LLM key queue order survives between ingest runs in `llm_key_queue`."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("asyncpg")

from tests.server import fresh_pool, pg_reachable


@pytest.mark.skipif(not pg_reachable(), reason="Postgres not reachable")
def test_moves_round_trip_and_keep_the_latest(monkeypatch):
    from finscrape.analysis import ai_client
    from server import db
    from worker import key_queue

    async def run():
        pool = await fresh_pool("llm_key_queue")
        try:
            monkeypatch.setattr(ai_client, "_moved_at", {"fa": 200.0, "fb": 100.0})
            await key_queue.save(pool)
            monkeypatch.setattr(ai_client, "_moved_at", {"fa": 150.0})
            await key_queue.save(pool)
            monkeypatch.setattr(ai_client, "_moved_at", {})
            await key_queue.load(pool)
            return dict(ai_client._moved_at)
        finally:
            await db.disconnect()

    assert asyncio.run(run()) == {"fa": 200.0, "fb": 100.0}
