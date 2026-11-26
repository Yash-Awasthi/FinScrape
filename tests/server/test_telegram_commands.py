"""Telegram /today, /ticker, /scenario and /help replies (no DB, no network).

The bot token path is owner-side; outbound HTTP is never attempted here because
`tg.send_message` is replaced with a recorder. The router is mounted on a throwaway
FastAPI app (like test_phase13) and the DB pool is a fake (like test_hardening).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes import telegram as tg
from server.settings import get_settings

WEBHOOK_SECRET = "s3cr3t-webhook-token"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class FakePool:
    """Records every query and answers with the rows the test handed it."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.queries: list[tuple[str, tuple]] = []

    async def fetch(self, query: str, *args):
        self.queries.append((query, args))
        return self.rows

    async def fetchrow(self, query: str, *args):
        self.queries.append((query, args))

    async def execute(self, *args):
        return


@pytest.fixture()
def bot(monkeypatch):
    """Secret configured, sends recorded, env restored on teardown."""
    sent: list[str] = []
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET_PREVIOUS", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(tg, "send_message", lambda chat_id, text: sent.append(text))
    app = FastAPI()
    app.include_router(tg.router)
    yield TestClient(app), sent
    get_settings.cache_clear()


def _post(client: TestClient, text: str, secret: str | None = WEBHOOK_SECRET):
    headers = {SECRET_HEADER: secret} if secret else {}
    return client.post(
        "/api/telegram/webhook",
        json={"message": {"chat": {"id": 42}, "text": text}},
        headers=headers,
    )


def test_today_lists_newest_rows_and_escapes_markdown(bot, monkeypatch):
    c, sent = bot
    fake = FakePool(
        [
            {"verdict": "INVEST", "subject": "Apple beats"},
            {"verdict": "PULL_OUT", "subject": "oil_price falls"},
        ]
    )
    monkeypatch.setattr(tg.db, "pool", lambda: fake)

    r = _post(c, "/today")

    assert r.status_code == 200 and r.json() == {"ok": True}
    assert sent == [
        (
            "Today (UTC):\n"
            "• INVEST Apple beats\n"
            r"• PULL\_OUT oil\_price falls"
        )
    ]
    assert "date_trunc('day'" in fake.queries[-1][0]


def test_today_says_so_when_empty(bot, monkeypatch):
    c, sent = bot
    monkeypatch.setattr(tg.db, "pool", lambda: FakePool([]))
    _post(c, "/today")
    assert sent == ["Today (UTC):\nNo signals today."]


def test_ticker_passes_argument_through_untouched(bot, monkeypatch):
    c, sent = bot
    fake = FakePool([{"verdict": "INVEST", "subject": "Apple beats"}])
    monkeypatch.setattr(tg.db, "pool", lambda: fake)

    r = _post(c, "/ticker aapl")

    assert r.status_code == 200
    assert "Ticker AAPL:" in sent[-1]
    assert "aapl" in fake.queries[-1][1]
    assert "jsonb_array_elements_text" in fake.queries[-1][0]


def test_ticker_without_argument_asks_for_one(bot):
    c, sent = bot
    _post(c, "/ticker")
    assert sent == ["Usage: /ticker AAPL"]


def test_scenario_reply_uses_id_title_and_probability(bot, monkeypatch):
    c, sent = bot

    async def fake_scenarios():
        return [
            {
                "id": "s12",
                "title": "Strait closure",
                "stance": "risk-on",
                "probability": 0.64,
            },
            {
                "id": "s3",
                "title": "Tariff round",
                "stance": "risk-off",
                "probability": 0.31,
            },
        ]

    monkeypatch.setattr(tg, "_load_scenarios", fake_scenarios)

    r = _post(c, "/scenario 12")

    assert r.status_code == 200
    assert "s12" in sent[-1]
    assert "Strait closure" in sent[-1]
    assert "64%" in sent[-1]
    assert "•" not in sent[-1]


def test_scenario_accepts_s_prefix_and_reports_missing(bot, monkeypatch):
    c, sent = bot

    async def fake_scenarios():
        return [
            {
                "id": "s12",
                "title": "Strait closure",
                "stance": "risk-on",
                "probability": 0.64,
            }
        ]

    monkeypatch.setattr(tg, "_load_scenarios", fake_scenarios)

    _post(c, "/scenario s12")
    assert "Strait closure" in sent[-1]

    _post(c, "/scenario 99")
    assert sent[-1] == "Scenario s99 not found."

    _post(c, "/scenario")
    assert sent[-1] == "Usage: /scenario 12"


def test_wrong_and_missing_secret_send_nothing(bot, monkeypatch):
    c, sent = bot
    monkeypatch.setattr(tg.db, "pool", lambda: FakePool([]))

    for secret in ("wrong", None):
        r = _post(c, "/today", secret=secret)
        assert r.status_code == 200 and r.json() == {"ok": True}

    assert sent == []


def test_help_lists_every_command(bot):
    c, sent = bot
    r = _post(c, "/help")
    assert r.status_code == 200
    for command in ("/latest", "/today", "/ticker", "/scenario"):
        assert command in sent[-1]
