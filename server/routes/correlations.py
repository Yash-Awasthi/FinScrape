"""GET /api/correlations?date= — correlation signals for a UTC day (Phase 4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder

from server import db
from server.ingest import day_bounds
from server.routes.params import day as day_param

router = APIRouter()


@router.get("/api/correlations")
async def list_correlations(
    date: str | None = Depends(day_param),
    limit: int = Query(200, ge=1, le=500),
) -> dict:
    if date:
        start, end = day_bounds(date)
        rows = await db.pool().fetch(
            "SELECT signal_type, confidence, payload, detected_at FROM correlations "
            "WHERE detected_at >= $1 AND detected_at < $2 ORDER BY detected_at DESC LIMIT $3",
            start,
            end,
            limit,
        )
    else:
        rows = await db.pool().fetch(
            "SELECT signal_type, confidence, payload, detected_at FROM correlations "
            "ORDER BY detected_at DESC LIMIT $1",
            limit,
        )
    return jsonable_encoder({"correlations": [dict(r) for r in rows]})
