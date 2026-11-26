"""Insight routes: calibrated predictions + reliability, from Postgres outcomes.

The CEIP engine (finscrape.signals.prediction) is pure — these routes feed it outcome
rows from `accuracy_outcomes` joined to `events` (for source/event_type/
confidence) and return the audited prediction payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from server import cache, db

log = logging.getLogger("worldfin.routes.insight")
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
    SELECT max(id) AS newest, count(*) AS considered,
           sum(length(articles::text)) AS coverage
    FROM (SELECT id, articles FROM events WHERE {_ANALYSED} ORDER BY id DESC LIMIT $1) w
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
        except ValueError, TypeError:
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
        except ValueError, TypeError:
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
    from finscrape.signals.prediction import brier_summary, reliability_tables

    outcomes = await _outcomes_from_pool()
    return {
        "reliability": reliability_tables(outcomes),
        "brier": brier_summary(outcomes),
    }


@router.get("/api/predict/{event_id}")
async def predict_event(event_id: int) -> dict:
    """Calibrated Event-Impact Probability for one stored event, with the
    reliability evidence attached (per verdict/source/type, sample sizes)."""
    from finscrape.signals.prediction import predict

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
    except ValueError, TypeError:
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
    except ValueError, TypeError:
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


# A scenario is rebuilt on a cache miss, so "history" means "what it said the last
# time it was computed". A row is kept when the number moved by at least 0.5 point or
# the last stored point is over an hour old; a page reload must not add a point.
_HISTORY_EPSILON = 0.005
_HISTORY_MAX_AGE_SECONDS = 3600


def should_record(
    previous: float | None, current: float, age_seconds: float | None
) -> bool:
    """Whether this recompute deserves a history row (pure, so it can be tested)."""
    if previous is None or age_seconds is None:
        return True
    return (
        abs(current - previous) >= _HISTORY_EPSILON
        or age_seconds >= _HISTORY_MAX_AGE_SECONDS
    )


async def _record_history(items: list[dict]) -> None:
    """Store the probability of each scenario that is new or has moved.

    Failing to write history must never fail the advice that was just computed.
    """
    try:
        for item in items:
            sid = item.get("id")
            if not sid:
                continue
            last = await db.pool().fetchrow(
                "SELECT probability, extract(epoch FROM now() - computed_at) AS age "
                "FROM scenario_history WHERE scenario_id = $1 "
                "ORDER BY computed_at DESC LIMIT 1",
                sid,
            )
            previous = float(last["probability"]) if last else None
            age = float(last["age"]) if last and last["age"] is not None else None
            current = float(item.get("probability") or 0.5)
            if not should_record(previous, current, age):
                continue
            await db.pool().execute(
                "INSERT INTO scenario_history (scenario_id, probability, n_members) "
                "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                sid,
                current,
                int(item.get("n_members") or item.get("size") or 0),
            )
    except Exception:
        log.warning("scenario history write failed", exc_info=True)


def _event_from_row(r: Any) -> dict[str, Any]:
    """One `_SCENARIO_COLUMNS` row as the dict the scenario engine grades."""
    return {
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


def _member_row(r: Any) -> dict:
    return {
        "id": r["id"],
        "subject": r["subject"],
        "verdict": r["verdict"],
        "signal_score": r["signal_score"],
        "confidence": float(r["confidence"] or 0.5),
        "sector_impact": r["sector_impact"] or "",
        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
        "sources": _jsonish(r["sources"], []),
    }


async def _what_if(
    item: dict[str, Any], ids: list[int], exclude: int, window: int
) -> dict[str, Any]:
    """Rebuild the scenario with one member dropped, for the what-if strip.

    Hypothetical only: nothing is stored and no history row is written, so the
    stored scenario keeps its probability.
    """
    if exclude not in ids:
        raise HTTPException(
            status_code=400,
            detail=f"exclude {exclude} is not a member of this scenario",
        )
    if len(ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="a scenario with one member cannot lose a member",
        )

    from finscrape.signals.scenarios import build_scenarios

    rows = await db.pool().fetch(_SCENARIO_COLUMNS, window)
    keep = set(ids) - {exclude}
    cluster = {
        "members": [_event_from_row(r) for r in rows if r["id"] in keep],
        "top_subject": item["title"],
        "reports": item.get("reports") or 0,
        "sources": item.get("sources") or [],
        "first_seen": item.get("first_seen"),
    }
    outcomes = await _outcomes_from_pool()
    built = await asyncio.to_thread(
        lambda: build_scenarios([cluster], outcomes, limit=1)
    )
    if not built:
        raise HTTPException(
            status_code=400, detail="the remaining members do not form a scenario"
        )
    rebuilt = built[0]
    return {
        "excluded_id": exclude,
        "probability": float(rebuilt["probability"]),
        "n_members": int(rebuilt["n_members"]),
        "ci95": rebuilt["ci95"],
        "label": "hypothetical: this member removed",
    }


@router.get("/api/scenarios/{scenario_id}")
async def scenario_detail(
    scenario_id: str,
    window: int = Query(200, ge=20, le=500),
    exclude: int | None = Query(None),
) -> dict:
    """One scenario with its member events and the window it was built from.

    The id is `s<min member id>`, so it is stable while those members stay in the
    window; a caller that lands on a stale id gets a 404 rather than a guess.
    `exclude` drops one member and recomputes, which the page shows as a what-if.
    """
    payload = await scenarios(limit=20, window=window)
    item = next((s for s in payload["scenarios"] if s["id"] == scenario_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    ids = [int(i) for i in item.get("member_ids") or [] if isinstance(i, int)]
    what_if = (
        await _what_if(item, ids, exclude, window) if exclude is not None else None
    )
    rows = (
        await db.pool().fetch(
            "SELECT id, subject, verdict, signal_score, confidence, sector_impact, "
            "timestamp, sources FROM events WHERE id = ANY($1::bigint[]) "
            "ORDER BY timestamp DESC",
            ids,
        )
        if ids
        else []
    )
    history = await db.pool().fetch(
        "SELECT probability, n_members, computed_at FROM scenario_history "
        "WHERE scenario_id = $1 ORDER BY computed_at DESC LIMIT 60",
        scenario_id,
    )
    return {
        "scenario": item,
        "members": [_member_row(r) for r in rows],
        "history": [
            {
                "probability": float(h["probability"]),
                "n_members": h["n_members"],
                "at": h["computed_at"].isoformat() if h["computed_at"] else None,
            }
            for h in reversed(history)
        ],
        "window": {
            "events_considered": payload.get("events_considered", 0),
            "event_cap": window,
            "lookback_days": 14,
        },
        "what_if": what_if,
    }


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
    from finscrape.signals.scenarios import build_scenarios

    # Settle a hit before paying for 200 event rows. Coverage merges add articles
    # to old rows without a new id, so their total size is part of the key.
    head = await db.pool().fetchrow(_SCENARIO_HEAD, window)
    newest, considered = (head["newest"] or 0), (head["considered"] or 0)
    key = f"scenarios:{newest}:{considered}:{head.get('coverage') or 0}:{limit}"
    hit = cache.peek(key)
    if hit is not cache.MISSING:
        return {"scenarios": hit, "events_considered": considered}

    rows = await db.pool().fetch(_SCENARIO_COLUMNS, window)
    events = [_event_from_row(r) for r in rows]
    outcomes = await _outcomes_from_pool()

    built = await asyncio.to_thread(
        lambda: cache.get_or_set(
            key,
            _SCENARIO_TTL,
            lambda: build_scenarios(build_storylines(events), outcomes, limit=limit),
        )
    )
    await _record_history(built)
    return {"scenarios": built, "events_considered": len(events)}
