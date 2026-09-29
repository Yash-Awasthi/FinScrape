"""Tests for finscrape.models data classes and enums."""

import pytest
from finscrape.models import Verdict, EventType, FinEvent, ScrapedArticle


# ---------------------------------------------------------------------------
# Verdict.from_score
# ---------------------------------------------------------------------------

class TestVerdictFromScore:
    """Verify the score-to-verdict mapping boundaries."""

    @pytest.mark.parametrize("score", [3, 4, 5, 10])
    def test_invest(self, score):
        assert Verdict.from_score(score) is Verdict.INVEST

    @pytest.mark.parametrize("score", [1, 2])
    def test_observe(self, score):
        assert Verdict.from_score(score) is Verdict.OBSERVE

    @pytest.mark.parametrize("score", [-2, -1, 0])
    def test_cautious(self, score):
        assert Verdict.from_score(score) is Verdict.CAUTIOUS

    @pytest.mark.parametrize("score", [-3, -5, -10])
    def test_pull_out(self, score):
        assert Verdict.from_score(score) is Verdict.PULL_OUT


# ---------------------------------------------------------------------------
# EventType enum values
# ---------------------------------------------------------------------------

class TestEventType:
    def test_earnings_value(self):
        assert EventType.EARNINGS.value == "earnings"

    def test_bankruptcy_value(self):
        assert EventType.BANKRUPTCY.value == "bankrupt"

    def test_ipo_value(self):
        assert EventType.IPO.value == "ipo"

    def test_other_value(self):
        assert EventType.OTHER.value == "other"

    def test_all_members_are_strings(self):
        for member in EventType:
            assert isinstance(member.value, str)

    def test_expected_member_count(self):
        assert len(EventType) == 15


# ---------------------------------------------------------------------------
# FinEvent
# ---------------------------------------------------------------------------

class TestFinEvent:
    def _make_event(self, **overrides) -> FinEvent:
        defaults = dict(
            subject="Apple earnings beat",
            event_type="earnings",
            tickers=["AAPL"],
            impact_direction="positive",
            signal_score=4,
            confidence=0.9,
            verdict="INVEST",
            heuristic_impact=0.75,
            divergence_flag=False,
            sources=["https://example.com/article"],
            articles=["Apple reported record Q1 revenue."],
            timestamp="2026-01-15T12:00:00+00:00",
        )
        defaults.update(overrides)
        return FinEvent(**defaults)

    def test_creation(self):
        ev = self._make_event()
        assert ev.subject == "Apple earnings beat"
        assert ev.tickers == ["AAPL"]
        assert ev.confidence == 0.9

    def test_to_dict_returns_dict(self):
        ev = self._make_event()
        d = ev.to_dict()
        assert isinstance(d, dict)
        assert d["subject"] == "Apple earnings beat"
        assert d["tickers"] == ["AAPL"]

    def test_from_dict_roundtrip(self):
        original = self._make_event()
        d = original.to_dict()
        restored = FinEvent.from_dict(d)
        assert restored.subject == original.subject
        assert restored.tickers == original.tickers
        assert restored.signal_score == original.signal_score
        assert restored.confidence == original.confidence
        assert restored.divergence_flag == original.divergence_flag

    def test_from_dict_ignores_extra_keys(self):
        d = self._make_event().to_dict()
        d["unknown_field"] = "should be ignored"
        ev = FinEvent.from_dict(d)
        assert ev.subject == "Apple earnings beat"

    def test_default_timestamp_set(self):
        ev = FinEvent(
            subject="X",
            event_type="other",
            tickers=[],
            impact_direction="neutral",
            signal_score=0,
            confidence=0.5,
            verdict="OBSERVE",
        )
        assert ev.timestamp  # non-empty string


# ---------------------------------------------------------------------------
# ScrapedArticle
# ---------------------------------------------------------------------------

class TestScrapedArticle:
    def test_is_fresh_when_young(self):
        art = ScrapedArticle(
            url="https://example.com/1",
            title="Title",
            text="x" * 200,
            source="test",
            age_hours=1.0,  # within the 2hr news window
        )
        assert art.is_fresh is True

    def test_is_fresh_at_boundary(self):
        art = ScrapedArticle(
            url="https://example.com/2",
            title="Title",
            text="x" * 200,
            source="test",
            age_hours=2.0,  # boundary of the default 2hr window (inclusive)
        )
        assert art.is_fresh is True

    def test_not_fresh_when_old(self):
        art = ScrapedArticle(
            url="https://example.com/3",
            title="Title",
            text="x" * 200,
            source="test",
            age_hours=25.0,
        )
        assert art.is_fresh is False

    def test_is_fresh_when_age_unknown(self):
        art = ScrapedArticle(
            url="https://example.com/4",
            title="Title",
            text="x" * 200,
            source="test",
        )
        assert art.is_fresh is True

    def test_has_content_true(self):
        art = ScrapedArticle(
            url="https://example.com/5",
            title="Good Title",
            text="A" * 150,
            source="test",
        )
        assert art.has_content is True

    def test_has_content_false_short_text(self):
        art = ScrapedArticle(
            url="https://example.com/6",
            title="Good Title",
            text="Too short",
            source="test",
        )
        assert art.has_content is False

    def test_has_content_false_no_title(self):
        art = ScrapedArticle(
            url="https://example.com/7",
            title="",
            text="A" * 200,
            source="test",
        )
        assert art.has_content is False

    def test_has_content_false_empty_text(self):
        art = ScrapedArticle(
            url="https://example.com/8",
            title="Title",
            text="",
            source="test",
        )
        assert art.has_content is False

    def test_has_content_false_whitespace_text(self):
        art = ScrapedArticle(
            url="https://example.com/9",
            title="Title",
            text="   ",
            source="test",
        )
        assert art.has_content is False
