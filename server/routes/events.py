"""Events ingest + feed + stats + dates. Root-cause bug fixes:
deterministic content_hash dedup, one UTC day-bounds convention, last_update=MAX(created_at).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.encoders import jsonable_encoder

from server import db, queries
from server.ai import analyze_event
from server.alert_rules import fire_alerts
from server.auth import require_api_key
from server.ingest import ingest_events
from server.routes.telegram import notify_new_events
from server.schemas import (
    DashboardStats,
    DatesResponse,
    IngestBatch,
    IngestResponse,
)
from server.settings import get_settings
from server.ws import hub

log = logging.getLogger("worldfin.routes.events")
router = APIRouter()


@router.post(
    "/api/events",
    response_model=IngestResponse,
    dependencies=[Depends(require_api_key)],
)
async def ingest(background: BackgroundTasks, payload: IngestBatch) -> IngestResponse:
    events = [e.model_dump() for e in payload.events]
    result = await ingest_events(db.pool(), events)

    if result["inserted_ids"]:
        # Live feed: broadcast the freshly inserted rows + new stats.
        rows = await db.pool().fetch(
            "SELECT * FROM events WHERE id = ANY($1::bigint[]) ORDER BY id",
            result["inserted_ids"],
        )
        await hub.broadcast(
            jsonable_encoder(
                {
                    "type": "new_events",
                    "events": [dict(r) for r in rows],
                    "stats": await queries.get_stats(db.pool()),
                }
            )
        )
        # Background AI expansion of just the NEW events (alert/analyze on insertedIds,
        # never raw input — fixes the re-alert-dupes bug). Non-blocking.
        if get_settings().has_llm:
            background.add_task(_background_ai, result["inserted_ids"])
        # Telegram alerts on the freshly inserted rows (no-op without a bot token and
        # subscribers). Alerts on insertedIds, never raw input.
        background.add_task(notify_new_events, result["inserted_rows"])
        background.add_task(fire_alerts, db.pool(), result["inserted_rows"])

    return IngestResponse(
        inserted=result["inserted"],
        duplicates=result["duplicates"],
        inserted_ids=result["inserted_ids"],
    )


async def _background_ai(event_ids: list[int]) -> None:
    """Analyze newly-ingested events off the request path, then notify clients once."""
    import hashlib

    model = get_settings().ai_model
    pool = db.pool()
    for eid in event_ids:
        try:
            event = await queries.get_event_by_id(pool, eid)
            if not event:
                continue
            cache_key = hashlib.sha256(f"{model}:{eid}".encode()).hexdigest()
            if await queries.get_ai_cache(pool, cache_key):
                continue
            result = await asyncio.to_thread(analyze_event, event)
            await queries.save_ai_cache(pool, cache_key, eid, result)
        # One event's failure spares the rest.
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            log.warning("background ai failed for event %s: %s", eid, exc)
    await hub.broadcast(
        jsonable_encoder({"type": "ai_updated", "stats": await queries.get_stats(pool)})
    )


@router.get("/api/events")
async def list_events(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    date: str | None = None,
    verdict: str | None = None,
    ticker: str | None = None,
    source: str | None = None,
    event_type: str | None = None,
    sort: str = "id",
    dir: str = "desc",
) -> dict:
    events = await queries.get_events(
        db.pool(),
        limit=limit,
        offset=offset,
        date=date,
        verdict=verdict,
        ticker=ticker,
        source=source,
        event_type=event_type,
        sort=sort,
        direction=dir,
    )
    return jsonable_encoder({"events": events})


@router.get("/api/stats", response_model=DashboardStats)
async def stats() -> DashboardStats:
    return DashboardStats(**await queries.get_stats(db.pool()))


@router.get("/api/dates", response_model=DatesResponse)
async def dates() -> DatesResponse:
    return DatesResponse.model_validate({"dates": await queries.get_dates(db.pool())})
