"""GET /api/accuracy — hit-rate, by-verdict, equity curve from accuracy_outcomes (Phase 7)."""

from __future__ import annotations

from fastapi import APIRouter

from server import db
from server.accuracy import aggregate, vs_spy_summary

router = APIRouter()


@router.get("/api/accuracy")
async def accuracy() -> dict:
    rows = await db.pool().fetch(
        "SELECT a.verdict, a.correct, a.correct2, a.correct4, a.price_move_pct, "
        "e.timestamp, e.confidence "
        "FROM accuracy_outcomes a JOIN events e ON a.event_id = e.id "
        "ORDER BY e.timestamp"
    )
    result = aggregate(
        [
            {
                "verdict": r["verdict"],
                "correct": r["correct"],
                "at": r["timestamp"].isoformat(),
                "move": r["price_move_pct"],
                "confidence": r["confidence"],
            }
            for r in rows
        ]
    )
    # Next-day raw move above; +2 / +4 trading days against SPY here.
    result["vs_spy"] = vs_spy_summary([dict(r) for r in rows])
    return result


@router.get("/api/accuracy/by-variant")
async def accuracy_by_variant() -> dict:
    """Hit-rate split by prompt A/B variant (Phase 13). Variant is read from the event's
    key_metrics; outcomes from variant-less events fall under 'v1'."""
    rows = await db.pool().fetch(
        "SELECT a.verdict, a.correct, a.price_move_pct, e.timestamp, e.confidence, "
        "COALESCE(e.key_metrics->>'prompt_variant', 'v1') AS variant "
        "FROM accuracy_outcomes a JOIN events e ON a.event_id = e.id "
        "ORDER BY e.timestamp"
    )
    by_variant: dict[str, list[dict]] = {}
    for r in rows:
        by_variant.setdefault(r["variant"], []).append(
            {
                "verdict": r["verdict"],
                "correct": r["correct"],
                "at": r["timestamp"].isoformat(),
                "move": r["price_move_pct"],
                "confidence": r["confidence"],
            }
        )
    return {variant: aggregate(rs) for variant, rs in by_variant.items()}
