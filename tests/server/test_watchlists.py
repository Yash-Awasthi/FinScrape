"""Watchlists: the model, the cascade, and the feed match (plan m4.1.1).

The UI (m4.1.2) is only as honest as this: an item is one of four kinds, the feed is
the union of matches, and deleting a list must not leave items behind. The DB half runs
against the test Postgres; the HTTP half uses a fake pool so it needs no database.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

asyncpg = pytest.importorskip("asyncpg")
pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import db, queries
from server.ingest import ingest_events
from server.routes import watchlists
from tests.server import PG_DSN as DSN

TEST_EVENT = Path(__file__).resolve().parent / "test_event.json"


def _pg_reachable() -> bool:
    async def _check() -> bool:
        try:
            conn = await asyncio.wait_for(asyncpg.connect(DSN), timeout=2)
        except TimeoutError, OSError, asyncpg.PostgresError:
            return False
        await conn.close()
        return True

    return asyncio.run(_check())


db_gated = pytest.mark.skipif(
    not _pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)


def _event(n: int, **overrides) -> dict:
    base = json.loads(TEST_EVENT.read_text())["events"][0]
    return {
        **base,
        "subject": f"Watchlist story {n}",
        "content_hash": f"watchlist-{n}",
        "timestamp": f"2026-05-03T0{n}:00:00Z",
        **overrides,
    }


# --- pure -------------------------------------------------------------------


def test_fold_groups_items_under_their_list() -> None:
    rows = [
        {
            "id": 2,
            "name": "Energy",
            "created_at": None,
            "item_id": 9,
            "kind": "ticker",
            "value": "XOM",
        },
        {
            "id": 2,
            "name": "Energy",
            "created_at": None,
            "item_id": 10,
            "kind": "sector",
            "value": "energy",
        },
        {
            "id": 1,
            "name": "Empty",
            "created_at": None,
            "item_id": None,
            "kind": None,
            "value": None,
        },
    ]
    lists = queries.fold_watchlists(rows)
    assert [w["name"] for w in lists] == ["Energy", "Empty"]
    assert lists[0]["items"] == [
        {"id": 9, "kind": "ticker", "value": "XOM"},
        {"id": 10, "kind": "sector", "value": "energy"},
    ]
    assert lists[1]["items"] == []


# --- DB ---------------------------------------------------------------------


@db_gated
def test_creating_a_list_and_matching_its_items() -> None:
    async def body():
        await db.disconnect()
        pool = await db.connect(DSN)
        await db.run_migrations(pool)
        # Two statements: the combined TRUNCATE with RESTART IDENTITY trips over a
        # cascaded table that has no identity column.
        await pool.execute("TRUNCATE events CASCADE")
        await pool.execute("TRUNCATE watchlists RESTART IDENTITY CASCADE")
        ids = (
            await ingest_events(
                pool,
                [
                    _event(1, tickers=["XOM"], sector_impact="energy, shipping"),
                    _event(2, tickers=["AAPL"], sector_impact="technology"),
                    _event(
                        3, tickers=["JPM"], subject="Hormuz shipping halt hits banks"
                    ),
                ],
            )
        )["inserted_ids"]
        watchlist = await queries.create_watchlist(
            pool,
            "default",
            "Energy book",
            [
                {"kind": "ticker", "value": "XOM"},
                {"kind": "sector", "value": "technology"},
                {"kind": "topic", "value": "Hormuz"},
            ],
        )
        feed = await queries.get_watchlist_feed(pool, watchlist["id"], "default", 50)
        other = await queries.get_watchlist_feed(
            pool, watchlist["id"], "someone-else", 50
        )
        await db.disconnect()
        assert watchlist["items"], "items were written with the list"
        # Union of the three kinds, newest first, no duplicates.
        assert [e["id"] for e in feed] == [ids[2], ids[1], ids[0]]
        assert other is None, "another owner cannot read this list"

    asyncio.run(body())


@db_gated
def test_deleting_a_list_leaves_no_orphan_items() -> None:
    async def body():
        await db.disconnect()
        pool = await db.connect(DSN)
        await db.run_migrations(pool)
        # Two statements: the combined TRUNCATE with RESTART IDENTITY trips over a
        # cascaded table that has no identity column.
        await pool.execute("TRUNCATE events CASCADE")
        await pool.execute("TRUNCATE watchlists RESTART IDENTITY CASCADE")
        watchlist = await queries.create_watchlist(
            pool, "default", "Temp", [{"kind": "ticker", "value": "XOM"}]
        )
        deleted = await queries.delete_watchlist(pool, "default", watchlist["id"])
        orphans = await pool.fetchval(
            "SELECT count(*) FROM watchlist_items WHERE watchlist_id = $1",
            watchlist["id"],
        )
        missing = await queries.delete_watchlist(pool, "default", watchlist["id"])
        await db.disconnect()
        assert deleted is True and missing is False
        assert orphans == 0, "ON DELETE CASCADE owns the cleanup"

    asyncio.run(body())


# --- HTTP -------------------------------------------------------------------


class _Pool:
    def __init__(self, rows=None, exists: bool = True):
        self.rows = rows or []
        self.exists = exists
        self.executed: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        return self.rows

    async def fetchval(self, sql, *args):
        return 1 if self.exists else None

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "DELETE 1"


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    app.include_router(watchlists.router)
    monkeypatch.setattr(db, "pool", lambda: _Pool())
    return TestClient(app)


def test_an_unknown_list_is_404(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(db, "pool", lambda: _Pool(exists=False))
    response = client.get("/api/watchlists/7/feed")
    assert response.status_code == 404


def test_an_owner_header_is_validated(client: TestClient) -> None:
    response = client.get("/api/watchlists", headers={"X-Watchlist-Owner": "bad key!"})
    assert response.status_code == 400


def test_writes_need_the_api_key(client: TestClient) -> None:
    assert client.post("/api/watchlists", json={"name": "x"}).status_code == 401
    assert client.delete("/api/watchlists/1").status_code == 401


def test_reader_endpoints_are_open(client: TestClient) -> None:
    assert client.get("/api/watchlists").status_code == 200
