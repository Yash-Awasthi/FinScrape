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


@pytest.mark.skipif(not pg_reachable(), reason="Postgres not reachable")
def test_a_429_key_stays_at_the_back_of_the_next_run(monkeypatch):
    """A run that spends a key must leave the queue rotated for the *next* run, not just
    for the rest of this one (plan m1.3.3)."""
    from finscrape.analysis import ai_client
    from server import db
    from worker import key_queue

    spent, fresh = "key-spent", "key-fresh"

    class Reply:
        def __init__(self, status: int):
            self.status_code = status
            self.text = "{}"

        def json(self):
            return {"error": {"message": "request_forbidden"}}

    def post(url, headers, json, timeout):
        return Reply(429 if spent in headers["Authorization"] else 200)

    async def run():
        pool = await fresh_pool("llm_key_queue")
        try:
            monkeypatch.setenv("OPENAI_API_KEY", spent)
            monkeypatch.setenv("OPENAI_API_KEYS", fresh)
            monkeypatch.setattr(ai_client, "_moved_at", {})
            monkeypatch.setattr(ai_client.requests, "post", post)
            # Run 1: the leading key answers 429, the second one answers.
            assert ai_client._proxy_keys()[0] == spent
            ai_client._call_openai_proxy("p", "s")
            await key_queue.save(pool)

            # Run 2 starts cold, in the state a new process would have.
            monkeypatch.setattr(ai_client, "_moved_at", {})
            await key_queue.load(pool)
            return ai_client._proxy_keys()
        finally:
            await db.disconnect()

    assert asyncio.run(run()) == [fresh, spent]
