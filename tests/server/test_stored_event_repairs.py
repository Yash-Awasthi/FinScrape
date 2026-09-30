"""Repairs to stored events: lost crypto alert punctuation and placeholder tickers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("asyncpg")

from tests.server import fresh_pool, pg_reachable

REPAIR = Path("server/migrations/0009_crypto_alert_subjects.sql").read_text()


@pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)
def test_stripped_crypto_subjects_get_sign_and_decimal_back():
    rows = [
        ("bitcoin cash bch dropped 98 in 24h", ["coingecko"]),
        ("stellar xlm surged 143 in 24h", ["coingecko"]),
        ("Bitcoin Cash (BCH) dropped -9.8% in 24h", ["coingecko"]),
        ("iran army surged 12 in 24h", ["world_rss"]),
    ]

    from server import db

    async def body():
        pool = await fresh_pool("events")
        for i, (subject, sources) in enumerate(rows):
            await pool.execute(
                "INSERT INTO events (content_hash, subject, event_type, verdict,"
                " sources, timestamp) VALUES ($1, $2, 'market_movement', 'OBSERVE',"
                " $3::jsonb, now())",
                f"h{i}",
                subject,
                sources,
            )
        await pool.execute(REPAIR)
        await pool.execute(REPAIR)
        try:
            return [
                r["subject"]
                for r in await pool.fetch("SELECT subject FROM events ORDER BY id")
            ]
        finally:
            await db.disconnect()

    assert asyncio.run(body()) == [
        "Bitcoin Cash (BCH) dropped -9.8% in 24h",
        "Stellar (XLM) surged +14.3% in 24h",
        "Bitcoin Cash (BCH) dropped -9.8% in 24h",
        "iran army surged 12 in 24h",
    ]


@pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)
def test_placeholder_tickers_are_removed_from_stored_events():
    from server import db

    sql = Path("server/migrations/0010_placeholder_tickers.sql").read_text()

    async def body():
        pool = await fresh_pool("events")
        for i, tickers in enumerate([["LMT", "N/A", "NONE"], ["—"], ["BRK-B"]]):
            await pool.execute(
                "INSERT INTO events (content_hash, subject, event_type, verdict,"
                " tickers, timestamp) VALUES ($1, 's', 'other', 'OBSERVE', $2, now())",
                f"t{i}",
                tickers,
            )
        await pool.execute(sql)
        try:
            return [
                r["tickers"]
                for r in await pool.fetch("SELECT tickers FROM events ORDER BY id")
            ]
        finally:
            await db.disconnect()

    assert asyncio.run(body()) == [["LMT"], [], ["BRK-B"]]
