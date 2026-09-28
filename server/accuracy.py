"""Accuracy backtest + aggregation (Phase 7 trust layer).

Ports the correctness rule from finscrape/accuracy.py (_determine_outcome): an INVEST is
right if price rose ≥1%, a PULL_OUT is right if it fell ≥1%; OBSERVE/CAUTIOUS are
non-directional (neutral). The pure helpers (verdict_outcome, aggregate) are unit-tested;
`backtest` takes an injectable price_fetcher so it runs offline in tests and against
finscrape market_data in the worker. `calibration` (Brier score + confidence buckets)
is shared with finscrape/accuracy.py rather than duplicated.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import asyncpg

from finscrape.accuracy import calibration, equity_metrics

THRESHOLD_PCT = 1.0
DIRECTIONAL = ("INVEST", "PULL_OUT")

# (tickers, event time, hours after) -> realized % move over that window, or None
PriceFetcher = Callable[[list[str], datetime, float], float | None]


def verdict_outcome(verdict: str, change_pct: float) -> str:
    """'correct' | 'incorrect' | 'neutral' — matches finscrape _determine_outcome."""
    if verdict not in DIRECTIONAL:
        return "neutral"
    if verdict == "INVEST":
        if change_pct >= THRESHOLD_PCT:
            return "correct"
        if change_pct <= -THRESHOLD_PCT:
            return "incorrect"
        return "neutral"
    # PULL_OUT
    if change_pct <= -THRESHOLD_PCT:
        return "correct"
    if change_pct >= THRESHOLD_PCT:
        return "incorrect"
    return "neutral"


def aggregate(rows: list[dict]) -> dict:
    """rows: {verdict, correct(bool|None), checked_at}. Returns hit-rate overall + by
    verdict + a cumulative equity curve (+1 correct / -1 incorrect, time-ordered)."""
    scored = [r for r in rows if r.get("correct") is not None]
    hits = sum(1 for r in scored if r["correct"])
    by_verdict: dict[str, dict] = {}
    for r in scored:
        b = by_verdict.setdefault(r["verdict"], {"hits": 0, "total": 0})
        b["total"] += 1
        if r["correct"]:
            b["hits"] += 1
    for b in by_verdict.values():
        b["hit_rate"] = round(b["hits"] / b["total"], 3) if b["total"] else 0.0

    equity: list[float] = []
    cum = 0.0
    for r in sorted(scored, key=lambda x: x.get("checked_at") or ""):
        cum += 1 if r["correct"] else -1
        equity.append(cum)

    # Per-step returns of the equity walk (each hit/miss relative to the stake so
    # far) feed the empyrical-backed metric engine — sharpe/sortino/drawdown.
    step_returns: list[float] = []
    prev = 0.0
    for value in equity:
        base = max(1.0, abs(prev))
        step_returns.append((value - prev) / base)
        prev = value

    return {
        "total": len(rows),
        "scored": len(scored),
        "hits": hits,
        "hit_rate": round(hits / len(scored), 3) if scored else 0.0,
        "by_verdict": by_verdict,
        "equity_curve": equity,
        "equity_metrics": equity_metrics(step_returns),
        "calibration": calibration(scored),
    }


async def backtest(
    pool: asyncpg.Pool,
    price_fetcher: PriceFetcher,
    *,
    hours_after: float = 24,
    lookback_days: int = 30,
    limit: int = 500,
) -> int:
    """Score directional events old enough to have a realized move, into
    accuracy_outcomes (idempotent — skips events already scored). Returns rows written."""
    events = await pool.fetch(
        """
        SELECT e.id, e.verdict, e.tickers, e.timestamp
        FROM events e
        WHERE e.verdict = ANY($1::text[])
          AND e.timestamp <= now() - ($2 || ' hours')::interval
          AND e.timestamp >= now() - ($3 || ' days')::interval
          AND jsonb_array_length(e.tickers) > 0
          AND NOT EXISTS (SELECT 1 FROM accuracy_outcomes a WHERE a.event_id = e.id)
        ORDER BY e.timestamp DESC LIMIT $4
        """,
        list(DIRECTIONAL),
        str(hours_after),
        str(lookback_days),
        limit,
    )
    written = 0
    for ev in events:
        tickers = ev["tickers"] or []
        change = price_fetcher(tickers, ev["timestamp"], hours_after)
        if change is None:
            continue
        outcome = verdict_outcome(ev["verdict"], change)
        correct = None if outcome == "neutral" else (outcome == "correct")
        # The SELECT above already skips scored events; this makes the skip authoritative
        # when two worker runs overlap, and keeps `written` a count of real writes.
        inserted = await pool.fetchval(
            "INSERT INTO accuracy_outcomes (event_id, ticker, verdict, price_move_pct, correct) "
            "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (event_id) DO NOTHING RETURNING id",
            ev["id"],
            tickers[0],
            ev["verdict"],
            change,
            correct,
        )
        if inserted is not None:
            written += 1
    return written
