"""Daily Telegram summary of the last 24 hours: `python -m worker.telegram_summary`.

Runs from the `telegram-summary` Action at 02:30 UTC (08:00 IST) and sends one message
to every subscribed chat. Live INVEST/PULL_OUT alerts go out from ingest separately.
"""

from __future__ import annotations

import asyncio
from collections import Counter

import asyncpg

from server import db
from server.routes.telegram import escape_md, send_message
from server.settings import get_settings

TOP_CALLS = 8
# Telegram rejects messages over 4096 characters.
MAX_CHARS = 4000


async def last_day(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        "SELECT subject, verdict, tickers, signal_score, confidence FROM events "
        "WHERE timestamp >= now() - interval '24 hours'"
    )
    return [dict(r) for r in rows]


def summary_text(events: list[dict]) -> str:
    if not events:
        return "📰 *WorldFin daily*\nNo new signals in the last 24 hours."
    counts = Counter(e.get("verdict") or "?" for e in events)
    order = ("INVEST", "PULL_OUT", "CAUTIOUS", "OBSERVE")
    tally = ", ".join(f"{v} {counts[v]}" for v in order if counts[v])
    calls = sorted(
        (e for e in events if e.get("verdict") in ("INVEST", "PULL_OUT")),
        key=lambda e: (abs(e.get("signal_score") or 0), e.get("confidence") or 0),
        reverse=True,
    )[:TOP_CALLS]
    lines = [f"📰 *WorldFin daily*: {len(events)} events ({escape_md(tally)})"]
    if calls:
        lines.append("\n*Strongest calls*")
        for e in calls:
            score = e.get("signal_score") or 0
            tickers = ", ".join((e.get("tickers") or [])[:3])
            lines.append(
                f"• {escape_md(e['verdict'])} ({score:+d}) {escape_md(tickers)}: {escape_md(e.get('subject') or '')}"
            )
    # Whole lines are dropped, never cut, so no Markdown escape is split in two.
    while len("\n".join(lines)) > MAX_CHARS and len(lines) > 1:
        lines.pop()
    return "\n".join(lines)[:MAX_CHARS]


async def main() -> int:
    pool = await db.connect(get_settings().database_url, min_size=1, max_size=2)
    try:
        text = summary_text(await last_day(pool))
        chats = [
            r["chat_id"]
            for r in await pool.fetch("SELECT chat_id FROM telegram_subscribers")
        ]
    finally:
        await db.disconnect()
    return sum(send_message(c, text) for c in chats)


if __name__ == "__main__":
    print(f"sent {asyncio.run(main())}")
