"""Weekly live scoring (docs/BACKFILL.md): `python -m worker.score_week`.

Runs from the `score-week` Action on Saturdays. Ingest scores calls from the last 30 days
every cycle; this sweep reaches a year back for calls a failed price fetch left open, then
prints the +2 / +4 day vs-SPY hit rates of the last two weeks' calls and of all calls.
"""

from __future__ import annotations

import asyncio

from finscrape.market_data import event_excess, event_moves
from server import db
from server.accuracy import backtest, score_vs_spy, vs_spy_summary
from server.settings import get_settings

LOOKBACK_DAYS = 365
LIMIT = 5000


def report(rows: list[dict]) -> str:
    """rows: {verdict, correct2, correct4, recent}."""
    lines = []
    for title, part in (
        ("last 14 days", [r for r in rows if r["recent"]]),
        ("all calls", rows),
    ):
        s = vs_spy_summary(part)
        rates = ", ".join(
            f"+{h} days {s[f'd{h}']['hit_rate']:.1%} of {s[f'd{h}']['scored']}"
            for h in (2, 4)
        )
        lines.append(f"{title}: {rates}")
    return "\n".join(lines)


async def main() -> int:
    pool = await db.connect(get_settings().database_url, min_size=1, max_size=2)
    try:
        wrote = await backtest(
            pool, event_moves, lookback_days=LOOKBACK_DAYS, limit=LIMIT
        )
        updated = await score_vs_spy(
            pool, event_excess, lookback_days=LOOKBACK_DAYS, limit=LIMIT
        )
        rows = await pool.fetch(
            "SELECT a.verdict, a.correct2, a.correct4, "
            "e.timestamp >= now() - interval '14 days' AS recent "
            "FROM accuracy_outcomes a JOIN events e ON a.event_id = e.id"
        )
    finally:
        await pool.close()
    # Rows whose +4 window is still open are re-updated every run, so this is not new scores.
    print(f"new outcomes {wrote}, vs-SPY rows updated {updated}")
    print(report([dict(r) for r in rows]))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
