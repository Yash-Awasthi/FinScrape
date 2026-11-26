"""Telegram bot webhook + outbound verdict alerts (Phase 13).

`POST /api/telegram/webhook` ALWAYS returns 200 immediately (Telegram retries otherwise)
and processes the command off the request path. Outbound INVEST/PULL_OUT alerts reuse the
finscrape alert message format and fan out to subscribers. Everything no-ops gracefully
when no `TELEGRAM_BOT_TOKEN` is set, so the rest of the app is unaffected.

Subscribers (chat_ids) live in the Postgres `telegram_subscribers` table.
"""

from __future__ import annotations

import asyncio
import hmac
import logging

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException
from fastapi import APIRouter, BackgroundTasks, Body, Header

from server import db, queries
from server.settings import get_settings

log = logging.getLogger("worldfin.telegram")
router = APIRouter()

_HELP = (
    "FinScrape bot commands:\n"
    "/subscribe — get INVEST/PULL\\_OUT alerts\n"
    "/unsubscribe — stop alerts\n"
    "/status — subscription + alert status\n"
    "/latest — most recent signals\n"
    "/today — newest signals since UTC midnight\n"
    "/ticker AAPL — recent signals for one ticker\n"
    "/scenario 12 — geopolitical scenario by id"
)

_TODAY_SQL = (
    "SELECT verdict, subject FROM events WHERE timestamp >= "
    "date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' "
    "ORDER BY timestamp DESC LIMIT 5"
)
_TICKER_SQL = (
    "SELECT verdict, subject FROM events WHERE EXISTS ("
    "SELECT 1 FROM jsonb_array_elements_text(tickers) AS t(value) "
    "WHERE lower(t.value) = lower($1)) ORDER BY timestamp DESC LIMIT 5"
)


async def _load_subs() -> set[str]:
    rows = await db.pool().fetch("SELECT chat_id FROM telegram_subscribers")
    return {r["chat_id"] for r in rows}


async def _load_scenarios() -> list[dict]:
    """Scenarios for /scenario; a module-level helper so tests can patch it."""
    from server.routes import insight

    payload = await insight.scenarios(limit=20)
    return payload.get("scenarios") or []


def send_message(chat_id: str | int, text: str) -> bool:
    """POST a message to a chat. No-op (False) when no bot token configured."""
    token = get_settings().telegram_bot_token
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.status_code == 200
    except RequestException as exc:  # pragma: no cover - network
        log.warning("telegram send failed: %s", exc)
        return False


def escape_md(text: str) -> str:
    """Escape Telegram legacy-Markdown markers; an unescaped one makes the send fail."""
    for ch in ("\\", "_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def format_alert(event: dict) -> str:
    """Same shape as finscrape.alerts AlertEngine._send_telegram_alert."""
    score = event.get("signal_score", 0)
    arrow = "+" if score >= 0 else ""
    text = (
        f"🚨 *{event.get('verdict', '?')}* ({arrow}{score}) — "
        f"{event.get('confidence', 0):.0%} confidence\n"
        f"Tickers: {escape_md(', '.join(event.get('tickers') or []))}\n"
        f"{escape_md(event.get('subject') or 'Unknown event')}"
    )
    reasoning = (event.get("reasoning") or "")[:200]
    return text + (f"\n_{escape_md(reasoning)}_" if reasoning else "")


async def notify_new_events(events: list[dict]) -> int:
    """Send directional (INVEST/PULL_OUT) events to all subscribers. Returns sends made."""
    if not get_settings().telegram_bot_token:
        return 0
    subs = await _load_subs()
    if not subs:
        return 0
    sent = 0
    for ev in events:
        if ev.get("verdict") not in ("INVEST", "PULL_OUT"):
            continue
        msg = format_alert(ev)
        for chat_id in subs:
            if await asyncio.to_thread(send_message, chat_id, msg):
                sent += 1
    return sent


async def _handle_command(chat_id: str, text: str) -> None:
    cmd = (
        text.strip().split()[0].lower().lstrip("/").split("@")[0]
        if text.strip()
        else ""
    )
    parts = text.strip().split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd in ("start", "help"):
        send_message(chat_id, _HELP)
    elif cmd == "subscribe":
        await db.pool().execute(
            "INSERT INTO telegram_subscribers (chat_id) VALUES ($1) ON CONFLICT DO NOTHING",
            str(chat_id),
        )
        send_message(chat_id, "✅ Subscribed to INVEST/PULL\\_OUT alerts.")
    elif cmd == "unsubscribe":
        await db.pool().execute(
            "DELETE FROM telegram_subscribers WHERE chat_id = $1", str(chat_id)
        )
        send_message(chat_id, "Unsubscribed.")
    elif cmd == "status":
        subbed = str(chat_id) in await _load_subs()
        send_message(chat_id, f"Alerts: {'on' if subbed else 'off'}.")
    elif cmd == "latest":
        rows = await queries.get_events(db.pool(), limit=5)
        lines = ["• " + escape_md(f"{r['verdict']} {r['subject']}") for r in rows] or [
            "No signals yet."
        ]
        send_message(chat_id, "Latest signals:\n" + "\n".join(lines))
    elif cmd == "today":
        rows = await db.pool().fetch(_TODAY_SQL)
        lines = ["• " + escape_md(f"{r['verdict']} {r['subject']}") for r in rows] or [
            "No signals today."
        ]
        send_message(chat_id, "Today (UTC):\n" + "\n".join(lines))
    elif cmd == "ticker":
        if not arg:
            send_message(chat_id, "Usage: /ticker AAPL")
            return
        rows = await db.pool().fetch(_TICKER_SQL, arg)
        lines = ["• " + escape_md(f"{r['verdict']} {r['subject']}") for r in rows] or [
            "No signals for that ticker."
        ]
        header = escape_md(f"Ticker {arg.upper()}:")
        send_message(chat_id, header + "\n" + "\n".join(lines))
    elif cmd == "scenario":
        if not arg:
            send_message(chat_id, "Usage: /scenario 12")
            return
        wanted = arg.lower()
        if not wanted.startswith("s"):
            wanted = f"s{wanted}"
        found = None
        for scenario in await _load_scenarios():
            if str(scenario.get("id")) == wanted:
                found = scenario
                break
        if found is None:
            send_message(chat_id, escape_md(f"Scenario {wanted} not found."))
            return
        pct = round(float(found.get("probability") or 0) * 100)
        send_message(
            chat_id,
            f"Scenario {found.get('id')} - {escape_md(found.get('title') or '')}\n"
            f"Stance: {found.get('stance')}, probability {pct}%",
        )


def _webhook_authentic(supplied: str | None) -> bool:
    """True only when Telegram's secret header matches the configured secret.

    Commands write the subscriber table and make the bot send messages to whatever
    chat id the body names, so an unauthenticated webhook is a spam relay. No secret
    configured means no request can be authenticated — the endpoint stays inert.
    """
    settings = get_settings()
    expected = tuple(
        secret
        for secret in (
            settings.telegram_webhook_secret,
            settings.telegram_webhook_secret_previous,
        )
        if secret
    )
    if not expected:
        log.warning(
            "TELEGRAM_WEBHOOK_SECRET is unset — /api/telegram/webhook ignores every "
            "update. Set it and pass the same value to setWebhook(secret_token=...)."
        )
        return False
    supplied_bytes = supplied.encode("utf-8") if supplied else b""
    matched = False
    for secret in expected:
        matched |= hmac.compare_digest(supplied_bytes, secret.encode("utf-8"))
    return bool(supplied) and matched


@router.post("/api/telegram/webhook")
async def webhook(
    background: BackgroundTasks,
    update: dict = Body(default={}),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Always 200. Command handling runs in the background so Telegram never retries."""
    if not _webhook_authentic(x_telegram_bot_api_secret_token):
        return {"ok": True}  # 200 regardless, so a bad sender learns nothing
    msg = (update or {}).get("message") or {}
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    text = msg.get("text") or ""
    if chat_id and text.startswith("/"):
        background.add_task(_handle_command, chat_id, text)
    return {"ok": True}
