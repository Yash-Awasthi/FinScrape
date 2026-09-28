"""GET /api/health — per-source freshness aggregate (Phase 3).

Distinct from the lightweight liveness `/health` in app.py: this rolls up
source_health (OK/STALE/WARN/EMPTY) and marks the whole service degraded if the DB is
down, any source isn't healthy, or half or more of the per-feed `world/*` rows aren't.
"""

from __future__ import annotations

from fastapi import APIRouter

from server import db
from server.schemas import HealthResponse, SourceHealth
from server.settings import get_settings
from worker.health import aggregate_health

router = APIRouter()

_UNHEALTHY = {"STALE", "WARN", "EMPTY"}


def sources_healthy(sources: list[SourceHealth]) -> bool:
    feeds = [src for src in sources if src.source.startswith("world/")]
    others = [src for src in sources if not src.source.startswith("world/")]
    dead_feeds = sum(src.status in _UNHEALTHY for src in feeds)
    return not any(src.status in _UNHEALTHY for src in others) and (
        not feeds or dead_feeds * 2 < len(feeds)
    )


@router.get("/api/health", response_model=HealthResponse)
async def api_health() -> HealthResponse:
    s = get_settings()
    pool = db.pool()

    db_ok = True
    try:
        await pool.fetchval("SELECT 1")
    except Exception:  # noqa: BLE001 - any DB failure reports degraded, never a 500
        db_ok = False

    sources = (
        [
            SourceHealth(**row)
            for row in await aggregate_health(pool, s.source_stale_after_minutes)
        ]
        if db_ok
        else []
    )
    healthy = db_ok and sources_healthy(sources)
    return HealthResponse(
        status="ok" if healthy else "degraded", db=db_ok, llm=s.has_llm, sources=sources
    )
