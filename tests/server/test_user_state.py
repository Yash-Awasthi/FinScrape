"""User state in Postgres (portfolio, Telegram subscribers, alert rules); needs a test DB."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("asyncpg")
pytest.importorskip("fastapi")

from fastapi import FastAPI

from tests.server import fresh_pool, pg_reachable

pytestmark = pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)

AUTH = {"X-API-Key": "local-dev-key"}


def test_portfolio_crud_persists_in_postgres(monkeypatch):
    import httpx2

    from server import db
    from server.routes import portfolio
    from server.settings import get_settings

    monkeypatch.setenv("FINSCRAPE_API_KEY", "local-dev-key")
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(portfolio.router)

    async def body():
        await fresh_pool("positions", "watchlists")
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://t") as c:
            position = {"ticker": "aapl", "shares": 10, "avg_cost": 150}
            r = await c.post("/api/portfolio/position", json=position, headers=AUTH)
            assert r.json()["ok"]
            got = (await c.get("/api/portfolio")).json()
            assert [p["ticker"] for p in got["positions"]] == ["AAPL"]
            assert got["summary"]["tickers"] == ["AAPL"]

            for tickers in (["msft"], ["nvda", "msft"]):
                body = {"name": "tech", "tickers": tickers}
                r = await c.post("/api/portfolio/watchlist", json=body, headers=AUTH)
            assert r.json()["watchlist"]["tickers"] == ["MSFT", "NVDA"]

            gone = "/api/portfolio/position?ticker=AAPL"
            assert (await c.delete(gone, headers=AUTH)).json()["ok"]
            assert not (await c.delete(gone, headers=AUTH)).json()["ok"]
            bad = {"ticker": "x", "shares": -1}
            r = await c.post("/api/portfolio/position", json=bad, headers=AUTH)
            assert r.status_code == 400
            r = await c.post("/api/portfolio/position", json={"ticker": "x"})
            assert r.status_code == 401
        await db.disconnect()

    try:
        asyncio.run(body())
    finally:
        get_settings.cache_clear()


def test_telegram_subscribers_persist_in_postgres(monkeypatch):
    from server import db
    from server.routes import telegram as tg

    monkeypatch.setattr(tg, "send_message", lambda chat_id, text: True)

    async def body():
        await fresh_pool("telegram_subscribers")
        await tg._handle_command("42", "/subscribe")
        await tg._handle_command("42", "/subscribe")
        await tg._handle_command("7", "/subscribe")
        assert await tg._load_subs() == {"42", "7"}
        await tg._handle_command("7", "/unsubscribe")
        assert await tg._load_subs() == {"42"}
        await db.disconnect()

    asyncio.run(body())


def test_alert_rules_crud_and_firing(monkeypatch):
    import httpx2

    from server import db
    from server.alert_rules import fire_alerts
    from server.routes import alerts
    from server.settings import get_settings

    monkeypatch.setenv("FINSCRAPE_API_KEY", "local-dev-key")
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(alerts.router)
    rule = {
        "name": "PULL_OUT on oil",
        "conditions": [
            {"field": "verdict", "operator": "eq", "value": "PULL_OUT"},
            {"field": "tickers", "operator": "contains", "value": "XOM"},
        ],
    }

    async def body():
        pool = await fresh_pool("alert_history", "alert_rules")
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/api/alerts/rules", json=rule, headers=AUTH)
            rule_id = r.json()["rule"]["id"]
            assert r.json()["rule"]["actions"] == [{"action_type": "log", "config": {}}]
            bad = {"name": "x", "conditions": [{"field": "nope", "operator": "eq"}]}
            r = await c.post("/api/alerts/rules", json=bad, headers=AUTH)
            assert r.status_code == 400
            assert (await c.post("/api/alerts/rules", json=rule)).status_code == 401

            hit = {"id": 1, "verdict": "PULL_OUT", "tickers": ["XOM", "CVX"]}
            miss = {"id": 2, "verdict": "INVEST", "tickers": ["XOM"]}
            assert await fire_alerts(pool, [hit, miss]) == 1
            row = await pool.fetchrow(
                "SELECT rule_id, event_id, status FROM alert_history"
            )
            assert dict(row) == {"rule_id": rule_id, "event_id": 1, "status": "ok"}

            off = {"enabled": False}
            r = await c.patch(f"/api/alerts/rules/{rule_id}", json=off, headers=AUTH)
            assert r.json()["ok"]
            assert await fire_alerts(pool, [hit]) == 0
            listed = (await c.get("/api/alerts/rules")).json()["rules"]
            assert [(x["id"], x["enabled"]) for x in listed] == [(rule_id, False)]

            gone = f"/api/alerts/rules/{rule_id}"
            assert (await c.delete(gone, headers=AUTH)).json()["ok"]
            assert not (await c.delete(gone, headers=AUTH)).json()["ok"]
        await db.disconnect()

    try:
        asyncio.run(body())
    finally:
        get_settings.cache_clear()


def test_backtest_skips_heuristic_fallback_events():
    from datetime import UTC, datetime, timedelta

    from server import db
    from server.accuracy import backtest

    async def body():
        pool = await fresh_pool("accuracy_outcomes", "events")
        when = datetime.now(UTC) - timedelta(days=3)
        for subject, variant in (("llm call", "v1"), ("fallback call", "heuristic")):
            await pool.execute(
                "INSERT INTO events (content_hash, subject, event_type, verdict, tickers,"
                " key_metrics, timestamp) VALUES ($1, $1, 'other', 'INVEST', $2, $3, $4)",
                subject,
                ["XOM"],
                {"prompt_variant": variant},
                when,
            )
        assert await backtest(pool, lambda tickers, at, hours: {"XOM": 2.0}) == 1
        scored = await pool.fetchval(
            "SELECT e.subject FROM accuracy_outcomes a JOIN events e ON e.id = a.event_id"
        )
        assert scored == "llm call"
        await db.disconnect()

    asyncio.run(body())


def test_feed_hides_events_the_llm_rejected():
    from datetime import UTC, datetime

    from server import db, queries

    async def body():
        pool = await fresh_pool("events")
        for subject, variant in (
            ("kept", "v1"),
            ("off topic", "rejected"),
            ("fallback", "heuristic"),
        ):
            await pool.execute(
                "INSERT INTO events (content_hash, subject, event_type, verdict, key_metrics,"
                " timestamp) VALUES ($1, $1, 'other', 'OBSERVE', $2, $3)",
                subject,
                {"prompt_variant": variant},
                datetime.now(UTC),
            )
        subjects = {e["subject"] for e in await queries.get_events(pool, limit=10)}
        assert subjects == {"kept", "fallback"}
        await db.disconnect()

    asyncio.run(body())
