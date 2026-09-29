"""Phase 13 — sentiment / telegram / prompt-A-B (no DB, no network).

Each route is mounted on a throwaway FastAPI app (like test_hardening) so we exercise
behaviour without the DB lifespan; network + Telegram sends are monkeypatched/no-op.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finscrape.analysis import prompt_registry as pr
from server import cache
from server.routes import sentiment as sentiment_routes
from server.routes import telegram as tg
from server.settings import get_settings

AUTH = {"X-API-Key": "local-dev-key"}


# --- prompt A/B registry ----------------------------------------------------
def test_pick_variant_off_is_v1(monkeypatch):
    monkeypatch.delenv("WORLDFIN_PROMPT_AB", raising=False)
    assert pr.pick_variant("any headline") == "v1"


def test_pick_variant_ab_deterministic_and_prompts_resolve(monkeypatch):
    monkeypatch.setenv("WORLDFIN_PROMPT_AB", "true")
    a = pr.pick_variant("Apple beats earnings")
    assert a == pr.pick_variant("Apple beats earnings")  # stable
    assert a in pr.VARIANT_IDS
    for v in pr.VARIANT_IDS:
        system, analysis = pr.get_prompts(v)
        assert system and "{{title}}" in analysis


# --- sentiment route --------------------------------------------------------
def _sentiment_client() -> TestClient:
    app = FastAPI()
    app.include_router(sentiment_routes.router)
    cache.clear()
    return TestClient(app)


def test_sentiment_degrades_to_empty_without_the_database():
    r = _sentiment_client().get("/api/sentiment?ticker=aapl")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL" and body["total_posts"] == 0


# --- telegram webhook -------------------------------------------------------
WEBHOOK_SECRET = "s3cr3t-webhook-token"


@pytest.fixture()
def telegram_client(monkeypatch):
    """Webhook router with a configured secret; commands are recorded, not run."""
    handled: list[tuple[str, str]] = []

    async def record(chat_id: str, text: str) -> None:
        handled.append((chat_id, text))

    monkeypatch.setattr(tg, "_handle_command", record)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(tg.router)
    yield TestClient(app), handled
    get_settings.cache_clear()


def test_telegram_webhook_runs_commands_with_the_secret_header(telegram_client):
    c, handled = telegram_client
    r = c.post(
        "/api/telegram/webhook",
        json={"message": {"chat": {"id": 42}, "text": "/subscribe"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert handled == [("42", "/subscribe")]


def test_telegram_webhook_ignores_updates_without_the_secret(telegram_client):
    """The URL is public and the body is attacker-written: no header, no command."""
    c, handled = telegram_client
    for headers in ({}, {"X-Telegram-Bot-Api-Secret-Token": "wrong"}):
        r = c.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": 42}, "text": "/subscribe"}},
            headers=headers,
        )
        assert r.status_code == 200 and r.json() == {"ok": True}  # never leaks
    assert handled == []


def test_telegram_webhook_inert_when_no_secret_configured(telegram_client, monkeypatch):
    c, handled = telegram_client
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    r = c.post(
        "/api/telegram/webhook",
        json={"message": {"chat": {"id": 42}, "text": "/subscribe"}},
    )
    assert r.status_code == 200
    assert handled == []


def test_telegram_notify_noop_without_token():
    # default settings carry no bot token → no sends, returns 0 (never raises)
    n = asyncio.run(
        tg.notify_new_events(
            [
                {
                    "verdict": "INVEST",
                    "subject": "x",
                    "tickers": ["AAPL"],
                    "signal_score": 3,
                }
            ]
        )
    )
    assert n == 0


def test_format_alert_shape():
    msg = tg.format_alert(
        {
            "verdict": "PULL_OUT",
            "signal_score": -3,
            "confidence": 0.8,
            "tickers": ["TSLA"],
            "subject": "recall",
        }
    )
    assert "PULL_OUT" in msg and "TSLA" in msg and "-3" in msg
