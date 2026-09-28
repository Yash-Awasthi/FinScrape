"""Tests for the email digest system."""

import os
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from finscrape.digest import DigestBuilder, EmailDigest


# --- Sample events ---

def make_event(verdict="INVEST", score=3, tickers=None, subject="Test event", **kwargs):
    return {
        "subject": subject,
        "event_type": kwargs.get("event_type", "earnings"),
        "tickers": tickers or ["AAPL"],
        "impact_direction": "positive" if score > 0 else "negative",
        "signal_score": score,
        "confidence": kwargs.get("confidence", 0.75),
        "verdict": verdict,
        "heuristic_impact": 0.5,
        "divergence_flag": False,
        "sources": ["yahoo"],
        "articles": ["https://example.com/article"],
        "timestamp": kwargs.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "reasoning": kwargs.get("reasoning", "Strong earnings beat with revenue growth"),
    }


class TestDigestBuilder:
    def test_daily_no_events(self):
        subject, html = DigestBuilder.build_daily([])
        assert "Daily Digest" in subject
        assert "No new signals" in html

    def test_daily_with_events(self):
        events = [
            make_event("INVEST", 4, ["AAPL", "MSFT"], "Apple beats earnings"),
            make_event("PULL_OUT", -3, ["TSLA"], "Tesla misses guidance"),
            make_event("OBSERVE", 1, ["GOOGL"], "Google launches product"),
            make_event("CAUTIOUS", -1, ["META"], "Meta regulatory concern"),
        ]
        subject, html = DigestBuilder.build_daily(events)

        assert "1 INVEST" in subject
        assert "1 PULL OUT" in subject
        assert "AAPL" in html
        assert "TSLA" in html
        assert "Apple beats earnings" in html
        assert "FinScrape" in html

    def test_daily_with_stats(self):
        events = [make_event()]
        stats = {"total_events": 42, "unique_tickers": 15, "sources_active": 5}
        subject, html = DigestBuilder.build_daily(events, stats)
        assert "42" in html
        assert "15" in html

    def test_daily_includes_reasoning(self):
        events = [make_event(reasoning="Strong earnings beat")]
        _, html = DigestBuilder.build_daily(events)
        assert "Strong earnings beat" in html

    def test_daily_limits_events_per_verdict(self):
        # 15 INVEST events — should only show 10
        events = [make_event("INVEST", 4, subject=f"Event {i}") for i in range(15)]
        _, html = DigestBuilder.build_daily(events)
        assert "Event 0" in html
        assert "Event 9" in html

    def test_weekly_no_events(self):
        subject, html = DigestBuilder.build_weekly([])
        assert "Weekly Digest" in subject
        assert "No signals this week" in html

    def test_weekly_with_events(self):
        events = [
            make_event("INVEST", 4, ["AAPL"], "Apple beats earnings"),
            make_event("INVEST", 3, ["AAPL"], "Apple raises guidance"),
            make_event("PULL_OUT", -4, ["TSLA"], "Tesla recall"),
            make_event("OBSERVE", 2, ["MSFT"], "Microsoft cloud growth"),
        ]
        subject, html = DigestBuilder.build_weekly(events)

        assert "Weekly Digest" in subject
        assert "AAPL (2)" in html  # top ticker count
        assert "Top Signals" in html
        assert "Week in Review" in html

    def test_weekly_top_tickers(self):
        events = [
            make_event("INVEST", 3, ["AAPL"]),
            make_event("INVEST", 3, ["AAPL"]),
            make_event("INVEST", 3, ["AAPL"]),
            make_event("OBSERVE", 1, ["MSFT"]),
        ]
        _, html = DigestBuilder.build_weekly(events)
        assert "AAPL (3)" in html

    def test_html_structure(self):
        _, html = DigestBuilder.build_daily([make_event()])
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "FinScrape" in html

    def test_weekly_sorts_by_absolute_score(self):
        events = [
            make_event("INVEST", 2, ["LOWSCORE"], subject="Low score event"),
            make_event("PULL_OUT", -5, ["HIGHNEG"], subject="High neg event"),
            make_event("INVEST", 5, ["HIGHPOS"], subject="High pos event"),
        ]
        _, html = DigestBuilder.build_weekly(events)
        # In the top signals table, high scores appear before low scores
        # Find them in the table body section (after "Top Signals" header)
        table_start = html.find("Top Signals")
        table_html = html[table_start:]
        pos_high = table_html.find("High pos event")
        pos_low = table_html.find("Low score event")
        assert pos_high < pos_low


class TestEmailDigest:
    def test_not_configured(self):
        digest = EmailDigest(proxy_url="", to_email="")
        assert not digest.is_configured
        result = digest.send_daily([])
        assert result.get("skipped")

    def test_configured(self):
        digest = EmailDigest(proxy_url="http://proxy", to_email="test@example.com")
        assert digest.is_configured

    @patch("finscrape.digest.requests.post")
    def test_send_daily_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "msg_123"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        digest = EmailDigest(
            proxy_url="http://proxy",
            to_email="test@example.com",
            from_email="from@example.com",
        )
        result = digest.send_daily([make_event()])
        assert result.get("ok")
        mock_post.assert_called_once()

        # Check the email payload
        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else json.loads(call_args[1].get("data", "{}"))
        assert payload["to"] == ["test@example.com"]
        assert "Daily" in payload["subject"]

    @patch("finscrape.digest.requests.post")
    def test_send_weekly_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "msg_456"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        digest = EmailDigest(
            proxy_url="http://proxy",
            to_email="test@example.com",
        )
        result = digest.send_weekly([make_event()])
        assert result.get("ok")

    @patch("finscrape.digest.requests.post")
    def test_send_failure(self, mock_post):
        import requests as req
        mock_post.side_effect = req.RequestException("Connection refused")

        digest = EmailDigest(
            proxy_url="http://proxy",
            to_email="test@example.com",
        )
        result = digest.send_daily([])
        assert "error" in result
