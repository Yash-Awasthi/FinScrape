"""Watchlists: a named set of things to follow, and the feed it produces.

Reads are scoped by an opaque owner key (`X-Watchlist-Owner`, default "default") so the
single-user dashboard needs no accounts; mutations need the ingest API key like every
other write. The model is m4.1.1 in `plan.md`, the UI is m4.1.2.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from server import db, queries
from server.auth import require_api_key
from server.correlate import annotate_topics
from server.schemas import WatchlistIn, WatchlistItemIn

router = APIRouter()

_OWNER = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def owner_key(header: str | None = Header(None, alias="X-Watchlist-Owner")) -> str:
    """Who the list belongs to. Not authentication: a label for a trusted single user,
    or the fingerprint the API-key middleware attaches once there are multiple users."""
    if header is None or header == "":
        return "default"
    if not _OWNER.match(header):
        raise HTTPException(status_code=400, detail="invalid X-Watchlist-Owner")
    return header


@router.get("/api/watchlists")
async def list_watchlists(owner: str = Depends(owner_key)) -> dict:
    return {"watchlists": await queries.list_watchlists(db.pool(), owner)}


@router.post(
    "/api/watchlists", dependencies=[Depends(require_api_key)], status_code=201
)
async def create_watchlist(
    payload: WatchlistIn, owner: str = Depends(owner_key)
) -> dict:
    try:
        watchlist = await queries.create_watchlist(
            db.pool(),
            owner,
            payload.name,
            [item.model_dump() for item in payload.items],
        )
    except Exception as exc:  # unique (owner_key, name) and the CHECK constraints
        name = type(exc).__name__
        if "UniqueViolation" in name:
            raise HTTPException(
                status_code=409, detail="a watchlist with that name exists"
            )
        if "CheckViolation" in name:
            raise HTTPException(status_code=400, detail="invalid watchlist value")
        raise
    return {"ok": True, "watchlist": watchlist}


@router.post(
    "/api/watchlists/{watchlist_id}/items",
    dependencies=[Depends(require_api_key)],
    status_code=201,
)
async def add_item(
    watchlist_id: int, payload: WatchlistItemIn, owner: str = Depends(owner_key)
) -> dict:
    item = await queries.add_watchlist_item(
        db.pool(), watchlist_id, owner, payload.kind, payload.value
    )
    if item is None:
        raise HTTPException(status_code=404, detail="watchlist not found")
    return {"ok": True, "item": item}


@router.delete(
    "/api/watchlists/{watchlist_id}/items/{item_id}",
    dependencies=[Depends(require_api_key)],
)
async def remove_item(
    watchlist_id: int, item_id: int, owner: str = Depends(owner_key)
) -> dict:
    removed = await queries.remove_watchlist_item(
        db.pool(), watchlist_id, owner, item_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="item not found")
    return {"ok": True, "id": item_id}


@router.delete(
    "/api/watchlists/{watchlist_id}", dependencies=[Depends(require_api_key)]
)
async def delete_watchlist(watchlist_id: int, owner: str = Depends(owner_key)) -> dict:
    deleted = await queries.delete_watchlist(db.pool(), owner, watchlist_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="watchlist not found")
    return {"ok": True, "id": watchlist_id}


@router.get("/api/watchlists/{watchlist_id}/feed")
async def watchlist_feed(
    watchlist_id: int,
    limit: int = Query(100, ge=1, le=500),
    owner: str = Depends(owner_key),
) -> dict:
    events = await queries.get_watchlist_feed(db.pool(), watchlist_id, owner, limit)
    if events is None:
        raise HTTPException(status_code=404, detail="watchlist not found")
    return {"events": annotate_topics(events)}
