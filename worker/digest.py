"""Email digest of recent signals from Postgres: `python -m worker.digest daily|weekly`.

Needs RESEND_PROXY_URL and FINSCRAPE_DIGEST_TO; run it from cron or a scheduled Action.
"""

from __future__ import annotations

import asyncio
import sys

import asyncpg

from finscrape.digest import EmailDigest
from server import db
from server.settings import get_settings

WINDOW_HOURS = {"daily": 24, "weekly": 24 * 7}


async def recent_events(pool: asyncpg.Pool, hours: int) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT subject, verdict, tickers, signal_score, confidence, reasoning, timestamp
        FROM events
        WHERE timestamp >= now() - make_interval(hours => $1)
        ORDER BY timestamp DESC
        """,
        hours,
    )
    return [{**dict(r), "timestamp": r["timestamp"].isoformat()} for r in rows]


async def send(kind: str) -> dict:
    digest = EmailDigest()
    if not digest.is_configured:
        return {
            "skipped": True,
            "reason": "set RESEND_PROXY_URL and FINSCRAPE_DIGEST_TO",
        }
    pool = await db.connect(get_settings().database_url, min_size=1, max_size=2)
    try:
        events = await recent_events(pool, WINDOW_HOURS[kind])
    finally:
        await db.disconnect()
    send_fn = digest.send_daily if kind == "daily" else digest.send_weekly
    return await asyncio.to_thread(send_fn, events)


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    if kind not in WINDOW_HOURS:
        sys.exit("usage: python -m worker.digest daily|weekly")
    print(asyncio.run(send(kind)))
