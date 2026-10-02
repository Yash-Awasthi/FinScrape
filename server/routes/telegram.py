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

import requests
from fastapi import APIRouter, BackgroundTasks, Body, Header

from server import db, queries
from server.settings import get_settings

log = logging.getLogger("worldfin.telegram")
router = APIRouter()

_HELP = (
    "WorldFin bot commands:\n"
    "/subscribe — get INVEST/PULL\\_OUT alerts\n"
    "/unsubscribe — stop alerts\n"
    "/status — subscription + alert status\n"
    "/latest — most recent signals"
)


async def _load_subs() -> set[str]:
    rows = await db.pool().fetch("SELECT chat_id FROM telegram_subscribers")
    return {r["chat_id"] for r in rows}


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
    except requests.RequestException as exc:  # pragma: no cover - network
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


def _webhook_authentic(supplied: str | None) -> bool:
    """True only when Telegram's secret header matches the configured secret.

    Commands write the subscriber table and make the bot send messages to whatever
    chat id the body names, so an unauthenticated webhook is a spam relay. No secret
    configured means no request can be authenticated — the endpoint stays inert.
    """
    expected = get_settings().telegram_webhook_secret
    if not expected:
        log.warning(
            "TELEGRAM_WEBHOOK_SECRET is unset — /api/telegram/webhook ignores every "
            "update. Set it and pass the same value to setWebhook(secret_token=...)."
        )
        return False
    return bool(supplied) and hmac.compare_digest(
        supplied.encode("utf-8"), expected.encode("utf-8")
    )


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
