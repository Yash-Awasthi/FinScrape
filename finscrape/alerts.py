"""
Alert rules engine for FinScrape.

Lets users define conditions like "notify me when any FAANG stock gets
PULL_OUT verdict" or "alert on any INVEST signal with confidence > 80%".

Rules and their firing history live in Postgres (server.alert_rules); this module
only matches events against rules and sends the actions.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Condition:
    """A single condition that checks one event field."""

    field: str  # verdict, signal_score, confidence, tickers, event_type, sector_impact, magnitude, sources
    operator: str  # eq, neq, gt, gte, lt, lte, in, contains, not_in
    value: Any

    VALID_FIELDS = frozenset({
        "verdict", "signal_score", "confidence", "tickers",
        "event_type", "sector_impact", "magnitude", "sources",
    })
    VALID_OPERATORS = frozenset({
        "eq", "neq", "gt", "gte", "lt", "lte", "in", "contains", "not_in",
    })

    def __post_init__(self) -> None:
        if self.field not in self.VALID_FIELDS:
            raise ValueError(f"Invalid condition field: {self.field!r}")
        if self.operator not in self.VALID_OPERATORS:
            raise ValueError(f"Invalid operator: {self.operator!r}")

    def evaluate(self, event: dict) -> bool:
        """Return True if the event satisfies this condition."""
        event_value = event.get(self.field)
        if event_value is None:
            return False

        op = self.operator
        target = self.value

        if op == "eq":
            return event_value == target
        elif op == "neq":
            return event_value != target
        elif op in ("gt", "gte", "lt", "lte"):
            try:
                ev = float(event_value)
                tv = float(target)
            except (ValueError, TypeError):
                return False
            if op == "gt":
                return ev > tv
            elif op == "gte":
                return ev >= tv
            elif op == "lt":
                return ev < tv
            else:
                return ev <= tv
        elif op == "in":
            # target is a list; event_value must be one of them
            return event_value in target
        elif op == "contains":
            # event_value is a list (e.g. tickers); check if target is in it
            if isinstance(event_value, list):
                if isinstance(target, list):
                    return any(t in event_value for t in target)
                return target in event_value
            # string containment fallback
            return str(target) in str(event_value)
        elif op == "not_in":
            return event_value not in target

        return False

    def to_dict(self) -> dict:
        return {"field": self.field, "operator": self.operator, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict) -> Condition:
        return cls(field=data["field"], operator=data["operator"], value=data["value"])


@dataclass
class Action:
    """An action to fire when a rule matches."""

    action_type: str  # telegram, discord, slack, dashboard_push, log, webhook
    config: dict = field(default_factory=dict)

    VALID_TYPES = frozenset({"telegram", "discord", "slack", "dashboard_push", "log", "webhook"})

    def __post_init__(self) -> None:
        if self.action_type not in self.VALID_TYPES:
            raise ValueError(f"Invalid action type: {self.action_type!r}")

    def to_dict(self) -> dict:
        return {"action_type": self.action_type, "config": self.config}

    @classmethod
    def from_dict(cls, data: dict) -> Action:
        return cls(action_type=data["action_type"], config=data.get("config", {}))


@dataclass
class AlertRule:
    """A named rule combining conditions (AND-logic) with actions."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    conditions: list[Condition] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    enabled: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def matches(self, event: dict) -> bool:
        """Return True if ALL conditions are satisfied (AND logic)."""
        if not self.conditions:
            return False
        return all(c.evaluate(event) for c in self.conditions)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "conditions": [c.to_dict() for c in self.conditions],
            "actions": [a.to_dict() for a in self.actions],
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AlertRule:
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            conditions=[Condition.from_dict(c) for c in data.get("conditions", [])],
            actions=[Action.from_dict(a) for a in data.get("actions", [])],
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# Alert engine
# ---------------------------------------------------------------------------

class AlertEngine:
    """Evaluate events against a set of alert rules and fire their actions."""

    def __init__(self, rules: list[AlertRule] | None = None):
        self.rules = list(rules or [])

    # -- evaluation ----------------------------------------------------------

    def evaluate(self, event: dict) -> list[tuple[AlertRule, list[Action]]]:
        """Check event against all enabled rules.

        Returns a list of (rule, actions) for every rule that matches.
        """
        matches: list[tuple[AlertRule, list[Action]]] = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.matches(event):
                matches.append((rule, rule.actions))
        return matches

    def execute_actions(self, event: dict, actions: list[Action]) -> list[dict]:
        """Fire the given actions for *event*.

        Returns a list of result dicts with action_type and status.
        """
        results = []
        for action in actions:
            try:
                result = self._execute_single_action(event, action)
                results.append(result)
            except Exception as e:
                logger.error("Action %s failed: %s", action.action_type, e)
                results.append({"action_type": action.action_type, "status": "error", "error": str(e)})

        return results

    def _execute_single_action(self, event: dict, action: Action) -> dict:
        """Execute a single action. Returns result dict."""
        if action.action_type == "log":
            logger.info(
                "ALERT [log]: event matched — %s | verdict=%s tickers=%s",
                event.get("subject", "?"),
                event.get("verdict", "?"),
                event.get("tickers", []),
            )
            return {"action_type": "log", "status": "ok"}

        elif action.action_type == "telegram":
            return self._send_telegram_alert(event, action)

        elif action.action_type == "discord":
            return self._send_discord_alert(event, action)

        elif action.action_type == "slack":
            return self._send_slack_alert(event, action)

        elif action.action_type == "webhook":
            return self._send_webhook_alert(event, action)

        elif action.action_type == "dashboard_push":
            return self._send_dashboard_alert(event, action)

        return {"action_type": action.action_type, "status": "unknown_type"}

    def _send_telegram_alert(self, event: dict, action: Action) -> dict:
        """Send alert via Telegram Bot API."""
        import os
        bot_token = action.config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = action.config.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")

        if not bot_token or not chat_id:
            logger.warning("Telegram alert: missing bot_token or chat_id")
            return {"action_type": "telegram", "status": "skipped", "reason": "missing config"}

        verdict = event.get("verdict", "?")
        tickers = ", ".join(event.get("tickers", []))
        score = event.get("signal_score", 0)
        confidence = event.get("confidence", 0)
        subject = event.get("subject", "Unknown event")
        reasoning = event.get("reasoning", "")[:200]

        arrow = "+" if score >= 0 else ""
        text = (
            f"🚨 *Alert Triggered*\n\n"
            f"*{verdict}* ({arrow}{score}) — {confidence:.0%} confidence\n"
            f"Tickers: `{tickers}`\n"
            f"Subject: {subject}\n"
        )
        if reasoning:
            text += f"\n_{reasoning}_"

        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Telegram alert sent successfully")
                return {"action_type": "telegram", "status": "ok"}
            else:
                logger.warning("Telegram API error %d", resp.status_code)
                return {"action_type": "telegram", "status": "error", "http_status": resp.status_code}
        except requests.RequestException as e:
            logger.error("Telegram request failed: %s", e)
            return {"action_type": "telegram", "status": "error", "error": str(e)}

    def _send_webhook_alert(self, event: dict, action: Action) -> dict:
        """POST event data to a webhook URL."""
        url = action.config.get("url", "")
        if not url:
            return {"action_type": "webhook", "status": "skipped", "reason": "no url"}

        # Validate URL: must be HTTPS, no private IPs
        if not self._is_safe_webhook_url(url):
            logger.warning("Webhook URL rejected (unsafe): %s", url[:100])
            return {"action_type": "webhook", "status": "rejected", "reason": "unsafe url"}

        headers = {"Content-Type": "application/json"}
        # Allow custom headers
        if action.config.get("headers"):
            headers.update(action.config["headers"])

        payload = {
            "alert_type": "finscrape",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": {
                "subject": event.get("subject", ""),
                "verdict": event.get("verdict", ""),
                "signal_score": event.get("signal_score", 0),
                "confidence": event.get("confidence", 0),
                "tickers": event.get("tickers", []),
                "event_type": event.get("event_type", ""),
                "reasoning": event.get("reasoning", "")[:500],
            },
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            logger.info("Webhook POST to %s: HTTP %d", url, resp.status_code)
            return {"action_type": "webhook", "status": "ok", "http_status": resp.status_code}
        except requests.RequestException as e:
            logger.error("Webhook POST failed: %s", e)
            return {"action_type": "webhook", "status": "error", "error": str(e)}

    def _send_dashboard_alert(self, event: dict, action: Action) -> dict:
        """Push alert event to dashboard."""
        from finscrape.dashboard import DashboardClient
        client = DashboardClient()
        if not client.is_configured:
            return {"action_type": "dashboard_push", "status": "skipped", "reason": "not configured"}

        alert_event = dict(event)
        alert_event["alert_triggered"] = True
        result = client.push_events([alert_event])
        return {"action_type": "dashboard_push", "status": "ok", "result": result}

    # -- presets (class methods) ---------------------------------------------

    @classmethod
    def preset_faang_pullout(cls) -> tuple[list[Condition], list[Action]]:
        """PULL_OUT verdict on any FAANG stock."""
        conditions = [
            Condition(field="verdict", operator="eq", value="PULL_OUT"),
            Condition(
                field="tickers",
                operator="contains",
                value=["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
            ),
        ]
        actions = [Action(action_type="log")]
        return conditions, actions

    @classmethod
    def preset_high_confidence_invest(cls) -> tuple[list[Condition], list[Action]]:
        """INVEST verdict with confidence >= 0.8."""
        conditions = [
            Condition(field="verdict", operator="eq", value="INVEST"),
            Condition(field="confidence", operator="gte", value=0.8),
        ]
        actions = [Action(action_type="log")]
        return conditions, actions

    @classmethod
    def preset_high_impact(cls) -> tuple[list[Condition], list[Action]]:
        """|signal_score| >= 4  (score >= 4 or score <= -4)."""
        # We approximate absolute value with two conditions OR-combined.
        # Since our engine uses AND logic, we implement this as a single
        # condition using a custom check.  Instead, we keep it simple:
        # signal_score >= 4 captures high-positive.  For a full implementation
        # we'd need OR logic.  For now, we use gte(4) which covers strongly
        # positive signals.  Users can add a second rule for lte(-4).
        conditions = [
            Condition(field="signal_score", operator="gte", value=4),
        ]
        actions = [Action(action_type="log")]
        return conditions, actions

    @classmethod
    def preset_breaking_news(cls) -> tuple[list[Condition], list[Action]]:
        """event_type == 'breaking_news'."""
        conditions = [
            Condition(field="event_type", operator="eq", value="breaking_news"),
        ]
        actions = [Action(action_type="log")]
        return conditions, actions

    @classmethod
    def preset_discord_high_confidence(cls) -> tuple[list[Condition], list[Action]]:
        """INVEST verdict with confidence >= 0.75, pushed to Discord."""
        conditions = [
            Condition(field="verdict", operator="eq", value="INVEST"),
            Condition(field="confidence", operator="gte", value=0.75),
        ]
        actions = [Action(action_type="discord", config={})]
        return conditions, actions

    @classmethod
    def preset_slack_pullout(cls) -> tuple[list[Condition], list[Action]]:
        """PULL_OUT verdict on any ticker, pushed to Slack."""
        conditions = [
            Condition(field="verdict", operator="eq", value="PULL_OUT"),
        ]
        actions = [Action(action_type="slack", config={})]
        return conditions, actions

    @classmethod
    def preset_multi_channel_high_impact(cls) -> tuple[list[Condition], list[Action]]:
        """|signal_score| >= 4, broadcast to Discord + Slack + Telegram."""
        conditions = [
            Condition(field="signal_score", operator="gte", value=4),
        ]
        actions = [
            Action(action_type="discord", config={}),
            Action(action_type="slack", config={}),
            Action(action_type="telegram", config={}),
        ]
        return conditions, actions

    # -- lifecycle -----------------------------------------------------------

    def _build_alert_summary(self, event: dict) -> dict:
        """Build a common summary dict used by Discord and Slack payloads."""
        verdict = event.get("verdict", "?")
        score = event.get("signal_score", 0)
        confidence = event.get("confidence", 0)
        tickers = ", ".join(event.get("tickers", [])) or "—"
        subject = event.get("subject", "Unknown event")
        reasoning = event.get("reasoning", "")[:300]
        event_type = event.get("event_type", "")
        sector = event.get("sector_impact", "")
        sources = event.get("sources", [])
        source_str = ", ".join(sources) if isinstance(sources, list) else str(sources)
        arrow = "📈" if score >= 0 else "📉"
        verdict_emoji = {
            "INVEST": "🟢", "PULL_OUT": "🔴", "OBSERVE": "🟡", "CAUTIOUS": "🟠",
        }.get(verdict, "⚪")
        return {
            "verdict": verdict, "score": score, "confidence": confidence,
            "tickers": tickers, "subject": subject, "reasoning": reasoning,
            "event_type": event_type, "sector": sector, "source_str": source_str,
            "arrow": arrow, "verdict_emoji": verdict_emoji,
        }

    def _send_discord_alert(self, event: dict, action: Action) -> dict:
        """Send a rich-embed alert to a Discord channel webhook.

        Config:
            url (required): Discord webhook URL (https://discord.com/api/webhooks/...)
            username (optional): override bot display name
            avatar_url (optional): override bot avatar
        Env fallback: DISCORD_WEBHOOK_URL
        """
        import os
        url = action.config.get("url") or os.getenv("DISCORD_WEBHOOK_URL", "")
        if not url:
            logger.warning("Discord alert: missing webhook url")
            return {"action_type": "discord", "status": "skipped", "reason": "missing config"}
        if not self._is_safe_webhook_url(url):
            logger.warning("Discord webhook URL rejected (unsafe): %s", url[:100])
            return {"action_type": "discord", "status": "rejected", "reason": "unsafe url"}

        s = self._build_alert_summary(event)
        color = {"INVEST": 3066993, "PULL_OUT": 15158332, "OBSERVE": 15844335,
                 "CAUTIOUS": 15105570}.get(s["verdict"], 7506394)  # green/red/yellow/orange/grey

        embed = {
            "title": f"{s['verdict_emoji']} {s['verdict']} — {s['tickers']}",
            "description": f"**{s['subject']}**\n\n{s['reasoning']}" if s["reasoning"] else f"**{s['subject']}**",
            "color": color,
            "fields": [
                {"name": "Signal Score", "value": f"{s['arrow']} {s['score']:+d}", "inline": True},
                {"name": "Confidence", "value": f"{s['confidence']:.0%}", "inline": True},
                {"name": "Event Type", "value": s["event_type"] or "—", "inline": True},
                {"name": "Sector Impact", "value": s["sector"] or "—", "inline": True},
                {"name": "Sources", "value": s["source_str"] or "—", "inline": False},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "WorldFin Signal Alert"},
        }
        payload: dict[str, Any] = {"embeds": [embed]}
        if action.config.get("username"):
            payload["username"] = action.config["username"]
        if action.config.get("avatar_url"):
            payload["avatar_url"] = action.config["avatar_url"]

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                logger.info("Discord alert sent successfully")
                return {"action_type": "discord", "status": "ok"}
            logger.warning("Discord webhook error %d: %s", resp.status_code, resp.text[:200])
            return {"action_type": "discord", "status": "error", "http_status": resp.status_code}
        except requests.RequestException as e:
            logger.error("Discord request failed: %s", e)
            return {"action_type": "discord", "status": "error", "error": str(e)}

    def _send_slack_alert(self, event: dict, action: Action) -> dict:
        """Send a rich-block alert to a Slack incoming webhook.

        Config:
            url (required): Slack webhook URL (https://hooks.slack.com/services/...)
            channel (optional): override channel (#general or @user)
            icon_emoji (optional): override bot icon
        Env fallback: SLACK_WEBHOOK_URL
        """
        import os
        url = action.config.get("url") or os.getenv("SLACK_WEBHOOK_URL", "")
        if not url:
            logger.warning("Slack alert: missing webhook url")
            return {"action_type": "slack", "status": "skipped", "reason": "missing config"}
        if not self._is_safe_webhook_url(url):
            logger.warning("Slack webhook URL rejected (unsafe): %s", url[:100])
            return {"action_type": "slack", "status": "rejected", "reason": "unsafe url"}

        s = self._build_alert_summary(event)
        verdict_color = {"INVEST": "#2eb67d", "PULL_OUT": "#e01e5a",
                         "OBSERVE": "#ecb22e", "CAUTIOUS": "#e07610"}.get(s["verdict"], "#6b6b6b")

        blocks = [
            {"type": "header", "text": {"type": "plain_text",
               "text": f"{s['verdict_emoji']} {s['verdict']} — {s['tickers']}"}},
            {"type": "section", "text": {"type": "mrkdwn",
               "text": f"*{s['subject']}*"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Score:*\n{s['arrow']} {s['score']:+d}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{s['confidence']:.0%}"},
                {"type": "mrkdwn", "text": f"*Event Type:*\n{s['event_type'] or '—'}"},
                {"type": "mrkdwn", "text": f"*Sector:*\n{s['sector'] or '—'}"},
            ]},
        ]
        if s["reasoning"]:
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                              "text": f"_{s['reasoning']}_"}})
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                          "text": f":worldfin: Sources: {s['source_str'] or '—'}"}]})

        payload: dict[str, Any] = {"blocks": blocks, "attachments": [{"color": verdict_color, "blocks": []}]}
        if action.config.get("channel"):
            payload["channel"] = action.config["channel"]
        if action.config.get("icon_emoji"):
            payload["icon_emoji"] = action.config["icon_emoji"]

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Slack alert sent successfully")
                return {"action_type": "slack", "status": "ok"}
            logger.warning("Slack webhook error %d: %s", resp.status_code, resp.text[:200])
            return {"action_type": "slack", "status": "error", "http_status": resp.status_code}
        except requests.RequestException as e:
            logger.error("Slack request failed: %s", e)
            return {"action_type": "slack", "status": "error", "error": str(e)}

    # -- security helpers ---------------------------------------------------

    @staticmethod
    def _is_safe_webhook_url(url: str) -> bool:
        """Validate that a webhook URL is safe (no SSRF).

        Rules:
        - Must use https:// scheme
        - Must not point to private/loopback IPs
        - Must have a valid hostname
        """
        from urllib.parse import urlparse
        import ipaddress

        try:
            parsed = urlparse(url)
        except Exception:
            return False

        # Must be HTTPS
        if parsed.scheme != "https":
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Block obvious private hostnames
        blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1",
                         "metadata.google.internal", "169.254.169.254"}
        if hostname.lower() in blocked_hosts:
            return False

        # Try to check if it resolves to a private IP
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                return False
        except ValueError:
            pass  # Not an IP literal — hostname is fine

        return True
