"""On-demand AI expansion: GET /api/ai/analyze?id= (cache → LLM → merge tickers)."""

from __future__ import annotations

import asyncio
import hashlib

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from server import db, queries
from server.ai import analyze_event
from server.settings import get_settings
from server.ws import hub

router = APIRouter()


@router.get("/api/ai/analyze")
async def analyze(id: int = Query(...)) -> dict:
    pool = db.pool()
    cache_key = hashlib.sha256(f"{get_settings().ai_model}:{id}".encode()).hexdigest()

    # Ingest stores an analysis per new event with its own model; any real one will do.
    cached = await queries.get_ai_cache_for_event(pool, id)
    if cached:
        return cached

    event = await queries.get_event_by_id(pool, id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    result = await asyncio.to_thread(analyze_event, event)
    if result.get("heuristic"):
        return result  # not cached, so a later request can still reach a model
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
