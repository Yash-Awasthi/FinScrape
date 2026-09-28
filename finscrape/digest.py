"""
Email digest system — sends daily/weekly summary emails of top financial signals.

Uses the Resend email proxy for delivery. Configure via environment variables:
    RESEND_PROXY_URL    — Resend proxy base URL (auto-set in camelAI)
    FINSCRAPE_DIGEST_TO — Recipient email address
    FINSCRAPE_DIGEST_FROM — Sender email (default: finscrape@notifications.camelai.app)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests


logger = logging.getLogger(__name__)


class DigestBuilder:
    """Builds HTML email digests from recent signals."""

    @staticmethod
    def build_daily(events: list[dict], stats: dict | None = None) -> tuple[str, str]:
        """Build a daily digest. Returns (subject, html_body)."""
        today = datetime.now(timezone.utc).strftime("%B %d, %Y")
        subject = f"FinScrape Daily Digest — {today}"

        if not events:
            html = DigestBuilder._wrap_html(
                f"<h2>Daily Digest — {today}</h2>"
                "<p>No new signals in the last 24 hours.</p>"
            )
            return subject, html

        # Group by verdict
        by_verdict: dict[str, list[dict]] = {}
        for e in events:
            v = e.get("verdict", "OBSERVE")
            by_verdict.setdefault(v, []).append(e)

        invest_count = len(by_verdict.get("INVEST", []))
        pullout_count = len(by_verdict.get("PULL_OUT", []))

        subject = f"FinScrape Daily: {invest_count} INVEST, {pullout_count} PULL OUT — {today}"

        sections = []

        # Stats summary
        if stats:
            sections.append(
                f'<div style="background:#1a1a2e;padding:16px;border-radius:8px;margin-bottom:20px;">'
                f'<h3 style="color:#10b981;margin:0 0 8px 0;">Pipeline Stats</h3>'
                f'<p style="color:#a1a1aa;margin:0;font-size:14px;">'
                f'Total signals: {stats.get("total_events", 0)} | '
                f'Tickers: {stats.get("unique_tickers", 0)} | '
                f'Sources: {stats.get("sources_active", 0)}'
                f'</p></div>'
            )

        # Signal sections ordered by priority
        for verdict, color, emoji in [
            ("INVEST", "#10b981", "&#x1F7E2;"),
            ("PULL_OUT", "#ef4444", "&#x1F534;"),
            ("OBSERVE", "#3b82f6", "&#x1F535;"),
            ("CAUTIOUS", "#f59e0b", "&#x1F7E1;"),
        ]:
            group = by_verdict.get(verdict, [])
            if not group:
                continue

            rows = ""
            for e in group[:10]:  # Limit to top 10 per verdict
                tickers = ", ".join(e.get("tickers", [])[:5])
                score = e.get("signal_score", 0)
                conf = e.get("confidence", 0)
                sign = "+" if score >= 0 else ""
                reasoning = e.get("reasoning", "")[:120]
                rows += (
                    f'<tr style="border-bottom:1px solid #27272a;">'
                    f'<td style="padding:8px;color:#e4e4e7;font-size:13px;">{e.get("subject", "")[:60]}</td>'
                    f'<td style="padding:8px;color:#a1a1aa;font-size:13px;">{tickers}</td>'
                    f'<td style="padding:8px;color:{color};font-weight:bold;font-size:13px;">{sign}{score}</td>'
                    f'<td style="padding:8px;color:#a1a1aa;font-size:13px;">{conf:.0%}</td>'
                    f'</tr>'
                )
                if reasoning:
                    rows += (
                        f'<tr style="border-bottom:1px solid #18181b;">'
                        f'<td colspan="4" style="padding:2px 8px 8px;color:#71717a;font-size:11px;font-style:italic;">'
                        f'{reasoning}</td></tr>'
                    )

            sections.append(
                f'<div style="margin-bottom:24px;">'
                f'<h3 style="color:{color};margin:0 0 8px 0;">{emoji} {verdict.replace("_", " ")} ({len(group)})</h3>'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<thead><tr style="border-bottom:1px solid #3f3f46;">'
                f'<th style="text-align:left;padding:6px 8px;color:#71717a;font-size:12px;">Subject</th>'
                f'<th style="text-align:left;padding:6px 8px;color:#71717a;font-size:12px;">Tickers</th>'
                f'<th style="text-align:left;padding:6px 8px;color:#71717a;font-size:12px;">Score</th>'
                f'<th style="text-align:left;padding:6px 8px;color:#71717a;font-size:12px;">Conf.</th>'
                f'</tr></thead><tbody>{rows}</tbody></table></div>'
            )

        body = (
            f'<h2 style="color:#e4e4e7;margin:0 0 16px 0;">Daily Digest — {today}</h2>'
            f'<p style="color:#a1a1aa;margin:0 0 20px 0;">'
            f'{len(events)} signals in the last 24 hours</p>'
            + "\n".join(sections)
        )

        return subject, DigestBuilder._wrap_html(body)

    @staticmethod
    def build_weekly(events: list[dict], stats: dict | None = None) -> tuple[str, str]:
        """Build a weekly digest. Returns (subject, html_body)."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        period = f"{start.strftime('%b %d')} — {end.strftime('%b %d, %Y')}"
        subject = f"FinScrape Weekly Digest — {period}"

        if not events:
            html = DigestBuilder._wrap_html(
                f"<h2>Weekly Digest — {period}</h2>"
                "<p>No signals this week.</p>"
            )
            return subject, html

        # Top tickers by frequency
        ticker_counts: dict[str, int] = {}
        for e in events:
            for t in e.get("tickers", []):
                ticker_counts[t] = ticker_counts.get(t, 0) + 1
        top_tickers = sorted(ticker_counts.items(), key=lambda x: -x[1])[:10]

        by_verdict: dict[str, int] = {}
        for e in events:
            v = e.get("verdict", "OBSERVE")
            by_verdict[v] = by_verdict.get(v, 0) + 1

        summary = (
            f'<div style="background:#1a1a2e;padding:16px;border-radius:8px;margin-bottom:20px;">'
            f'<h3 style="color:#10b981;margin:0 0 12px 0;">Week in Review</h3>'
            f'<p style="color:#a1a1aa;margin:0 0 8px 0;font-size:14px;">'
            f'Total signals: {len(events)}</p>'
            f'<p style="color:#a1a1aa;margin:0 0 8px 0;font-size:14px;">'
            f'INVEST: {by_verdict.get("INVEST", 0)} | '
            f'PULL OUT: {by_verdict.get("PULL_OUT", 0)} | '
            f'OBSERVE: {by_verdict.get("OBSERVE", 0)} | '
            f'CAUTIOUS: {by_verdict.get("CAUTIOUS", 0)}</p>'
        )

        if top_tickers:
            ticker_str = ", ".join(f"{t} ({c})" for t, c in top_tickers)
            summary += (
                f'<p style="color:#a1a1aa;margin:0;font-size:14px;">'
                f'Top tickers: {ticker_str}</p>'
            )
        summary += '</div>'

        # Top signals (highest absolute score)
        top_events = sorted(events, key=lambda e: abs(e.get("signal_score", 0)), reverse=True)[:15]

        rows = ""
        for e in top_events:
            verdict = e.get("verdict", "OBSERVE")
            color = {"INVEST": "#10b981", "PULL_OUT": "#ef4444", "OBSERVE": "#3b82f6"}.get(verdict, "#f59e0b")
            tickers = ", ".join(e.get("tickers", [])[:3])
            score = e.get("signal_score", 0)
            sign = "+" if score >= 0 else ""
            rows += (
                f'<tr style="border-bottom:1px solid #27272a;">'
                f'<td style="padding:8px;color:{color};font-weight:bold;font-size:13px;">{verdict.replace("_", " ")}</td>'
                f'<td style="padding:8px;color:#e4e4e7;font-size:13px;">{e.get("subject", "")[:50]}</td>'
                f'<td style="padding:8px;color:#a1a1aa;font-size:13px;">{tickers}</td>'
                f'<td style="padding:8px;color:{color};font-weight:bold;font-size:13px;">{sign}{score}</td>'
                f'</tr>'
            )

        top_section = (
            f'<h3 style="color:#e4e4e7;margin:0 0 8px 0;">Top Signals</h3>'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr style="border-bottom:1px solid #3f3f46;">'
            f'<th style="text-align:left;padding:6px 8px;color:#71717a;font-size:12px;">Verdict</th>'
            f'<th style="text-align:left;padding:6px 8px;color:#71717a;font-size:12px;">Subject</th>'
            f'<th style="text-align:left;padding:6px 8px;color:#71717a;font-size:12px;">Tickers</th>'
            f'<th style="text-align:left;padding:6px 8px;color:#71717a;font-size:12px;">Score</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

        body = (
            f'<h2 style="color:#e4e4e7;margin:0 0 16px 0;">Weekly Digest — {period}</h2>'
            + summary + top_section
        )

        return subject, DigestBuilder._wrap_html(body)

    @staticmethod
    def _wrap_html(body: str) -> str:
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
            '<body style="margin:0;padding:0;background:#09090b;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">'
            '<div style="max-width:640px;margin:0 auto;padding:24px;">'
            '<div style="text-align:center;margin-bottom:24px;">'
            '<span style="color:#10b981;font-weight:bold;font-size:20px;">Fin</span>'
            '<span style="color:#e4e4e7;font-weight:bold;font-size:20px;">Scrape</span>'
            '</div>'
            f'{body}'
            '<div style="margin-top:32px;padding-top:16px;border-top:1px solid #27272a;'
            'text-align:center;color:#52525b;font-size:11px;">'
            'FinScrape — AI-powered financial news intelligence'
            '</div></div></body></html>'
        )


class EmailDigest:
    """Sends email digests via the Resend proxy."""

    def __init__(
        self,
        proxy_url: str | None = None,
        to_email: str | None = None,
        from_email: str | None = None,
    ):
        self.proxy_url = (proxy_url or os.getenv("RESEND_PROXY_URL", "")).rstrip("/")
        self.to_email = to_email or os.getenv("FINSCRAPE_DIGEST_TO", "")
        self.from_email = from_email or os.getenv("FINSCRAPE_DIGEST_FROM", "finscrape@notifications.camelai.app")
        self.builder = DigestBuilder()

    @property
    def is_configured(self) -> bool:
        return bool(self.proxy_url and self.to_email)

    def send_daily(self, events: list[dict]) -> dict:
        """Send the daily digest for `events` (the caller picks the last 24h)."""
        if not self.is_configured:
            return {"skipped": True, "reason": "not configured"}

        subject, html = self.builder.build_daily(events)
        return self._send(subject, html)

    def send_weekly(self, events: list[dict]) -> dict:
        """Send the weekly digest for `events` (the caller picks the last 7 days)."""
        if not self.is_configured:
            return {"skipped": True, "reason": "not configured"}

        subject, html = self.builder.build_weekly(events)
        return self._send(subject, html)

    def _send(self, subject: str, html: str) -> dict:
        """Send email via Resend proxy."""
        try:
            resp = requests.post(
                f"{self.proxy_url}/emails",
                json={
                    "from": self.from_email,
                    "to": [self.to_email],
                    "subject": subject,
                    "html": html,
                },
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info("Sent digest email: %s -> %s", subject, self.to_email)
            return {"ok": True, **result}
        except requests.RequestException as e:
            logger.warning("Failed to send digest email: %s", e)
            return {"error": str(e)}
