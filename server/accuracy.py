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

# (tickers, event time, hours after) -> realized % move per ticker over that window
PriceFetcher = Callable[[list[str], datetime, float], dict[str, float]]

_IMPACT_SIGN = {"positive": 1, "negative": -1}


def called_move(
    verdict: str, entities: list[dict], moves: dict[str, float]
) -> float | None:
    """Mean move in the direction the analysis called for each ticker.

    A PULL_OUT on a conflict story still names defence stocks as winners; scoring
    their rise against the verdict counted a right call as wrong. A ticker takes its
    entity's impact sign when the analysis gave one, else the verdict's.
    """
    default = 1 if verdict == "INVEST" else -1
    signs = {
        str(e.get("ticker") or "").upper(): _IMPACT_SIGN[str(e.get("impact"))]
        for e in entities or []
        if isinstance(e, dict) and str(e.get("impact")) in _IMPACT_SIGN
    }
    signed = [signs.get(t.upper(), default) * m for t, m in moves.items()]
    return round(sum(signed) / len(signed), 4) if signed else None


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
        SELECT e.id, e.verdict, e.tickers, e.timestamp, e.affected_entities
        FROM events e
        WHERE e.verdict = ANY($1::text[])
          AND e.timestamp <= now() - ($2 || ' hours')::interval
          AND e.timestamp >= now() - ($3 || ' days')::interval
          AND jsonb_array_length(e.tickers) > 0
          -- The record measures the analysis engine, not the keyword fallback
          -- that stands in while the LLM is down.
          AND coalesce(e.key_metrics->>'prompt_variant', '') <> 'heuristic'
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
        moves = price_fetcher(tickers, ev["timestamp"], hours_after)
        change = called_move(ev["verdict"], ev["affected_entities"] or [], moves)
        if change is None:
            continue
        # `change` is already signed toward the call, so INVEST's rule applies.
        outcome = verdict_outcome("INVEST", change)
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


# (tickers, event time) -> {horizon: {ticker: % return minus SPY's}}
ExcessFetcher = Callable[[list[str], datetime], dict[int, dict[str, float]]]


async def score_vs_spy(
    pool: asyncpg.Pool,
    excess_fetcher: ExcessFetcher,
    *,
    lookback_days: int = 30,
    limit: int = 500,
) -> int:
    """Fill ex2/ex4 on scored calls: the called-direction return over SPY's, +2 and +4
    trading days on. A call hits when it beat SPY that way; no band. Returns rows updated."""
    rows = await pool.fetch(
        """
        SELECT a.id, a.verdict, e.tickers, e.timestamp, e.affected_entities
        FROM accuracy_outcomes a JOIN events e ON a.event_id = e.id
        WHERE a.ex4 IS NULL
          AND e.timestamp <= now() - interval '2 days'
          AND e.timestamp >= now() - ($1 || ' days')::interval
        ORDER BY e.timestamp LIMIT $2
        """,
        str(lookback_days),
        limit,
    )
    updated = 0
    for r in rows:
        excess = excess_fetcher(r["tickers"] or [], r["timestamp"])
        ex = [
            called_move(r["verdict"], r["affected_entities"] or [], excess.get(h, {}))
            for h in (2, 4)
        ]
        if ex[0] is None:
            continue
        hit = [None if x is None or x == 0 else x > 0 for x in ex]
        await pool.execute(
            "UPDATE accuracy_outcomes SET ex2 = $2, ex4 = $3, correct2 = $4, correct4 = $5 WHERE id = $1",
            r["id"],
            *ex,
            *hit,
        )
        updated += 1
    return updated


def vs_spy_summary(rows: list[dict]) -> dict:
    """Hit rate per horizon from rows {verdict, correct2, correct4}; open windows skipped."""
    out = {}
    for h in (2, 4):
        agg = aggregate(
            [{"verdict": r["verdict"], "correct": r[f"correct{h}"]} for r in rows]
        )
        out[f"d{h}"] = {k: agg[k] for k in ("scored", "hits", "hit_rate", "by_verdict")}
    return out
