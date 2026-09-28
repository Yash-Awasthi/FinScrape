"""Portfolio + watchlist routes (Phase 13), stored in Postgres.

Rows are shaped by finscrape's Position/Watchlist so the payload matches what the
standalone PortfolioManager returns.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from finscrape.portfolio import Position, Watchlist
from server import db
from server.auth import require_api_key

router = APIRouter()


async def _positions() -> list[Position]:
    rows = await db.pool().fetch(
        "SELECT ticker, shares, avg_cost, current_price, tags FROM positions ORDER BY ticker"
    )
    return [Position(**dict(r)) for r in rows]


async def _watchlists() -> list[Watchlist]:
    rows = await db.pool().fetch(
        "SELECT name, tickers, description FROM watchlists ORDER BY name"
    )
    return [Watchlist(**dict(r)) for r in rows]


@router.get("/api/portfolio")
async def get_portfolio() -> dict:
    positions = await _positions()
    watchlists = await _watchlists()
    held = {p.ticker for p in positions}
    watched = held.union(*(w.tickers for w in watchlists))
    return {
        "positions": [p.to_dict() for p in positions],
        "watchlists": [w.to_dict() for w in watchlists],
        "summary": {
            "positions": len(positions),
            "total_value": round(sum(p.market_value for p in positions), 2),
            "total_pnl": round(sum(p.unrealized_pnl for p in positions), 2),
            "tickers": sorted(held),
            "watchlists": [w.to_dict() for w in watchlists],
            "watched_tickers": sorted(watched),
        },
    }


@router.post("/api/portfolio/position", dependencies=[Depends(require_api_key)])
async def add_position(payload: dict = Body(...)) -> dict:
    ticker = str(payload.get("ticker", "")).upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="ticker required")
    try:
        shares = float(payload.get("shares", 0))
        avg_cost = float(payload.get("avg_cost", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="shares/avg_cost must be numbers")
    if shares < 0 or avg_cost < 0:
        raise HTTPException(status_code=400, detail="shares/avg_cost must be >= 0")
    await db.pool().execute(
        """
        INSERT INTO positions (ticker, shares, avg_cost) VALUES ($1, $2, $3)
        ON CONFLICT (ticker) DO UPDATE
            SET shares = excluded.shares, avg_cost = excluded.avg_cost, updated_at = now()
        """,
        ticker,
        shares,
        avg_cost,
    )
    return {"ok": True, "ticker": ticker}


@router.delete("/api/portfolio/position", dependencies=[Depends(require_api_key)])
async def remove_position(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    status = await db.pool().execute("DELETE FROM positions WHERE ticker = $1", ticker)
    return {"ok": status != "DELETE 0", "ticker": ticker}


@router.post("/api/portfolio/watchlist", dependencies=[Depends(require_api_key)])
async def upsert_watchlist(payload: dict = Body(...)) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    tickers = [str(t).upper().strip() for t in (payload.get("tickers") or []) if t]
    row = await db.pool().fetchrow(
        """
        INSERT INTO watchlists (name, tickers) VALUES ($1, $2)
        ON CONFLICT (name) DO UPDATE SET tickers = (
            SELECT coalesce(jsonb_agg(DISTINCT t ORDER BY t), '[]')
            FROM jsonb_array_elements(watchlists.tickers || excluded.tickers) AS t
        )
        RETURNING name, tickers, description
        """,
        name,
        tickers,
    )
    return {"ok": True, "watchlist": Watchlist(**dict(row)).to_dict()}


@router.delete("/api/portfolio/watchlist", dependencies=[Depends(require_api_key)])
async def delete_watchlist(name: str) -> dict:
    name = name.strip()
    status = await db.pool().execute("DELETE FROM watchlists WHERE name = $1", name)
    return {"ok": status != "DELETE 0", "name": name}
