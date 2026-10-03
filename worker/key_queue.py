"""Keeps the LLM key queue order (`ai_client`) in Postgres between runs, so a key
spent in one ingest run stays at the back in the next.

One read when a run starts; a write at its end only for keys that answered 429.
"""

from __future__ import annotations

import datetime as dt

import asyncpg

from finscrape.analysis import ai_client

_loaded: dict[str, float] = {}


async def load(pool: asyncpg.Pool) -> None:
    rows = await pool.fetch("SELECT fingerprint, moved_at FROM llm_key_queue")
    _loaded.clear()
    _loaded.update({r["fingerprint"]: r["moved_at"].timestamp() for r in rows})
    ai_client.load_key_moves(_loaded)


async def save(pool: asyncpg.Pool) -> None:
    moved = [(fp, t) for fp, t in ai_client.key_moves().items() if _loaded.get(fp) != t]
    if not moved:
        return
    # GREATEST: an `analyze` run finishing late must not pull a key forward.
    await pool.executemany(
        "INSERT INTO llm_key_queue (fingerprint, moved_at) VALUES ($1, $2) "
        "ON CONFLICT (fingerprint) DO UPDATE "
        "SET moved_at = GREATEST(llm_key_queue.moved_at, EXCLUDED.moved_at)",
        [(fp, dt.datetime.fromtimestamp(t, dt.UTC)) for fp, t in moved],
    )
