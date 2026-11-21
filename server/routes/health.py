"""GET /api/health — per-source freshness aggregate (Phase 3).

Distinct from the lightweight liveness `/health` in app.py: this rolls up
source_health (OK/STALE/WARN/EMPTY) and marks the whole service degraded if the DB is
down, any source isn't healthy, or half or more of the per-feed `world/*` rows aren't.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from server import db
from server.schemas import HealthResponse, SourceHealth
from server.settings import get_settings
from worker.health import aggregate_health

logger = logging.getLogger(__name__)

router = APIRouter()

_UNHEALTHY = {"STALE", "WARN", "EMPTY"}

# Above this share of the last 24 h, the feed is mostly keyword output, so the judged
# verdicts are not what a reader thinks they are (plan m1.3.2).
HEURISTIC_ALERT_SHARE = 0.20


async def heuristic_share(pool) -> float | None:
    """Share of the last 24 h of events written by the fallback. None when there were no
    events at all — a quiet feed is not evidence of health."""
    row = await pool.fetchrow(
        "SELECT count(*) FILTER (WHERE analysis_source = 'heuristic') AS h, count(*) AS n "
        "FROM events WHERE timestamp >= now() - interval '24 hours'"
    )
    if not row or not row["n"]:
        return None
    return round(row["h"] / row["n"], 3)


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
    except Exception:
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
    share = await heuristic_share(pool) if db_ok else None
    alert = share is not None and share > HEURISTIC_ALERT_SHARE
    if alert and share is not None:
        logger.warning(
            "heuristic_share_24h %.1f%% exceeds %.0f%% — most recent events are not "
            "model-judged",
            share * 100,
            HEURISTIC_ALERT_SHARE * 100,
        )
    return HealthResponse(
        status="ok" if healthy else "degraded",
        db=db_ok,
        llm=s.has_llm,
        sources=sources,
        heuristic_share_24h=share,
        heuristic_alert=alert,
    )
