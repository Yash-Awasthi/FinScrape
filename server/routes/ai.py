"""On-demand AI expansion: GET /api/ai/analyze?id= (cache → LLM → merge tickers)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from server import db, queries
from server.ai import analyze_event, heuristic_answer
from server.settings import get_settings
from server.ws import hub

router = APIRouter()
log = logging.getLogger("worldfin.ai")

# A dispatched job usually lands in 1-2 minutes; polls inside this window only read
# the cache, so waiting on the job never spends the API's own model quota.
_DISPATCH_WINDOW_S = 600.0
_dispatched: dict[int, float] = {}
# The route is public: a loop over event ids must not turn into a loop of jobs.
_recent_dispatches: deque[float] = deque()


def _dispatch_job(event_id: int) -> bool:
    """Start the `analyze` workflow for one event. True when it is (already) running."""
    s = get_settings()
    if not (s.analyze_dispatch_repo and s.analyze_dispatch_token):
        return False
    now = time.monotonic()
    if now - _dispatched.get(event_id, -_DISPATCH_WINDOW_S) < _DISPATCH_WINDOW_S:
        return True
    while _recent_dispatches and now - _recent_dispatches[0] > 3600:
        _recent_dispatches.popleft()
    if len(_recent_dispatches) >= s.analyze_dispatch_per_hour:
        log.warning("analyze dispatch cap reached; event %s left heuristic", event_id)
        return False
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{s.analyze_dispatch_repo}"
            "/actions/workflows/analyze.yml/dispatches",
            headers={
                "Authorization": f"Bearer {s.analyze_dispatch_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"ref": s.analyze_dispatch_ref, "inputs": {"event_id": str(event_id)}},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("analyze dispatch failed for event %s: %s", event_id, exc)
        return False
    _dispatched[event_id] = now
    _recent_dispatches.append(now)
    return True


@router.get("/api/ai/analyze")
async def analyze(id: int = Query(...)) -> dict:
    pool = db.pool()
    cache_key = hashlib.sha256(f"{get_settings().ai_model}:{id}".encode()).hexdigest()

    # Any real stored analysis will do, whichever model or job wrote it.
    cached = await queries.get_ai_cache_for_event(pool, id)
    if cached:
        return cached

    event = await queries.get_event_by_id(pool, id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    waited = time.monotonic() - _dispatched.get(id, -_DISPATCH_WINDOW_S)
    if waited < _DISPATCH_WINDOW_S:
        return {**heuristic_answer(event), "pending": True}

    result = await asyncio.to_thread(analyze_event, event)
    if result.get("heuristic"):
        # Not cached, so a later click can still reach a model.
        return {**result, "pending": await asyncio.to_thread(_dispatch_job, id)}
    merged = await queries.save_ai_cache(pool, cache_key, id, result)
    # If AI discovered new tickers, tell live clients to refresh.
    if len(merged) > len(event.get("tickers") or []):
        await hub.broadcast(
            jsonable_encoder(
                {"type": "ai_updated", "stats": await queries.get_stats(pool)}
            )
        )
    return result


@router.get("/api/ai/council")
async def council(id: int = Query(...)) -> dict:
    """Explainability: multi-agent council verdict + dissent for an event. Behind the
    WORLDFIN_ENABLE_COUNCIL flag; needs an LLM backend (runs in a thread)."""
    if not get_settings().enable_council:
        raise HTTPException(status_code=404, detail="council disabled")
    event = await queries.get_event_by_id(db.pool(), id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    def run() -> dict:
        from finscrape.agents import DEFAULT_AGENTS, AgentCouncil

        verdict = AgentCouncil(agents=DEFAULT_AGENTS).deliberate(
            event["subject"],
            event.get("reasoning") or event["subject"],
            {"source": (event.get("sources") or [None])[0]},
        )
        return {
            "consensus_verdict": verdict.consensus_verdict,
            "consensus_score": verdict.consensus_score,
            "agreement_level": verdict.agreement_level,
            "dissenting_agents": verdict.dissenting_agents,
            "key_risks": verdict.key_risks,
            "key_opportunities": verdict.key_opportunities,
        }

    return await asyncio.to_thread(run)
