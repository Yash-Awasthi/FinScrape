"""Insight routes: calibrated predictions + reliability, from Postgres outcomes.

The CEIP engine (finscrape.prediction) is pure — these routes feed it outcome
rows from `accuracy_outcomes` joined to `events` (for source/event_type/
confidence) and return the audited prediction payload.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from server import cache, db

router = APIRouter()

# Scenarios advise only from recent LLM-analysed news: keyword-fallback verdicts,
# rows the LLM rejected as off-topic, month-old news and the retired CoinGecko
# price-move rows would steer the advice.
_ANALYSED = (
    "coalesce(key_metrics->>'prompt_variant', '') NOT IN ('heuristic', 'rejected') "
    "AND timestamp > now() - interval '14 days' AND NOT sources ? 'coingecko'"
)

# Columns the scenario engine grades on. `/api/storylines` needs far fewer, so
# this query is its own rather than a widened share.
_SCENARIO_COLUMNS = f"""
    SELECT id, subject, reasoning, verdict, signal_score, confidence, event_type,
           magnitude, actionability, sector_impact, divergence_flag,
           tickers, sources, articles, affected_entities, second_order_effects,
           created_at
    FROM events WHERE {_ANALYSED} ORDER BY id DESC LIMIT $1
"""

# Newest id keys the cache — a new event is the only thing that can change the
# answer inside the TTL — and the row count tells the key which window it is.
_SCENARIO_HEAD = f"""
    SELECT max(id) AS newest, count(*) AS considered
    FROM (SELECT id FROM events WHERE {_ANALYSED} ORDER BY id DESC LIMIT $1) w
"""

# Clustering embeds every distinct subject through Ollama, so an uncached
# /api/scenarios would spend seconds per caller for an answer that changes only
# as fast as new events land.
_SCENARIO_TTL = cache.MEDIUM


def _jsonish(value: Any, fallback: Any) -> Any:
    """asyncpg hands JSONB back as str on some drivers and as the value on others."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return fallback
    return value if value is not None else fallback


async def _outcomes_from_pool() -> list[dict[str, Any]]:
    rows = await db.pool().fetch(
        """
        SELECT o.verdict, o.correct, o.checked_at,
               e.confidence, e.event_type, e.sources
        FROM accuracy_outcomes o
        LEFT JOIN events e ON e.id = o.event_id
        WHERE o.correct IS NOT NULL
        ORDER BY o.checked_at
        """
    )
    outcomes: list[dict[str, Any]] = []
    for r in rows:
        sources = []
        try:
            sources = (
                json.loads(r["sources"])
                if isinstance(r["sources"], str)
                else (r["sources"] or [])
            )
        except (ValueError, TypeError):
            sources = []
        outcomes.append(
            {
                "verdict": r["verdict"],
                "outcome": "correct" if r["correct"] else "incorrect",
                "confidence": r["confidence"],
                "source": (sources[0].split("/")[-1] if sources else "unknown"),
                "event_type": r["event_type"] or "other",
                "checked_at": r["checked_at"].isoformat() if r["checked_at"] else None,
            }
        )
    return outcomes


@router.get("/api/reliability")
async def reliability() -> dict:
    """Reliability tables + Brier score — the audit view of prediction quality."""
    from finscrape.prediction import brier_summary, reliability_tables

    outcomes = await _outcomes_from_pool()
    return {
        "reliability": reliability_tables(outcomes),
        "brier": brier_summary(outcomes),
    }


@router.get("/api/predict/{event_id}")
async def predict_event(event_id: int) -> dict:
    """Calibrated Event-Impact Probability for one stored event, with the
    reliability evidence attached (per verdict/source/type, sample sizes)."""
    from finscrape.prediction import predict

    ev = await db.pool().fetchrow(
        """
        SELECT id, subject, reasoning, verdict, signal_score, confidence,
               event_type, sources, tickers
        FROM events WHERE id = $1
        """,
        event_id,
    )
    if ev is None:
        raise HTTPException(status_code=404, detail="event not found")

    sources: list[str] = []
    try:
        raw_sources = ev["sources"]
        sources = (
            json.loads(raw_sources)
            if isinstance(raw_sources, str)
            else (raw_sources or [])
        )
    except (ValueError, TypeError):
        sources = []
    source = sources[0].split("/")[-1] if sources else "local"
    tickers: list[str] = []
    try:
        raw_tickers = ev["tickers"]
        tickers = (
            json.loads(raw_tickers)
            if isinstance(raw_tickers, str)
            else (raw_tickers or [])
        )
    except (ValueError, TypeError):
        tickers = []

    outcomes = await _outcomes_from_pool()
    result = predict(
        text=f"{ev['subject']}. {ev['reasoning']}"
        if ev["reasoning"]
        else ev["subject"],
        verdict=ev["verdict"],
        confidence=float(ev["confidence"] or 0.5),
        source=source,
        event_type=ev["event_type"] or "other",
        outcomes=outcomes,
    )
    result["event"] = {
        "id": ev["id"],
        "subject": ev["subject"],
        "verdict": ev["verdict"],
        "signal_score": ev["signal_score"],
        "ticker": (tickers[0] if tickers else ""),
    }
    return result


@router.get("/api/scenarios")
async def scenarios(
    limit: int = Query(6, ge=1, le=20),
    window: int = Query(200, ge=20, le=500),
) -> dict:
    """Geopolitical scenarios: recent events clustered, scored and turned into
    one instruction each.

    A scenario carries the same calibrated probability the per-event
    `/api/predict` would give its members, plus the net sector and ticker tilt
    that probability implies — the advice, rather than the evidence.
    """
    from finscrape.analysis.clusters import build_storylines
    from finscrape.scenarios import build_scenarios

    # The cache key needs only the newest id and how many rows the window holds,
    # so settle a hit before paying for 200 event rows and every scored outcome.
    head = await db.pool().fetchrow(_SCENARIO_HEAD, window)
    newest, considered = (head["newest"] or 0), (head["considered"] or 0)
    key = f"scenarios:{newest}:{considered}:{limit}"
    hit = cache.peek(key)
    if hit is not cache.MISSING:
        return {"scenarios": hit, "events_considered": considered}

    rows = await db.pool().fetch(_SCENARIO_COLUMNS, window)
    events = [
        {
            "id": r["id"],
            "subject": r["subject"],
            "reasoning": r["reasoning"] or "",
            "verdict": r["verdict"],
            "signal_score": r["signal_score"],
            "confidence": r["confidence"],
            "event_type": r["event_type"],
            "magnitude": r["magnitude"],
            "actionability": r["actionability"],
            "sector_impact": r["sector_impact"] or "",
            "divergence_flag": bool(r["divergence_flag"]),
            "tickers": _jsonish(r["tickers"], []),
            "sources": _jsonish(r["sources"], []),
            "articles": _jsonish(r["articles"], []),
            "affected_entities": _jsonish(r["affected_entities"], []),
            "second_order_effects": _jsonish(r["second_order_effects"], []),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    outcomes = await _outcomes_from_pool()

    built = await asyncio.to_thread(
        lambda: cache.get_or_set(
            key,
            _SCENARIO_TTL,
            lambda: build_scenarios(build_storylines(events), outcomes, limit=limit),
        )
    )
    return {"scenarios": built, "events_considered": len(events)}
