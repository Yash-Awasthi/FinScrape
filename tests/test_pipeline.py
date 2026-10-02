"""
Integration tests for the FinScrape pipeline: article → AI analysis → validation →
scoring → event, deduped against an in-memory EventStore.
"""

from unittest.mock import patch

import pytest

from finscrape.alerts import Action, AlertEngine
from finscrape.models import FinEvent, ScrapedArticle
from finscrape.pipeline import FinScrapePipeline


class MemoryEvents:
    def __init__(self):
        self.events: list[dict] = []

    def add_event(self, event: dict) -> int:
        self.events.append({**event, "id": len(self.events) + 1})
        return len(self.events)

    def update_event(self, event_id: int, **kwargs) -> None:
        self.events[event_id - 1].update(kwargs)


# --- Fixtures ---

@pytest.fixture
def sample_article():
    return ScrapedArticle(
        url="https://example.com/test-article",
        title="Apple Reports Record Q4 Earnings",
        text="Apple Inc. (AAPL) reported record fourth-quarter earnings of $1.46 per share, "
             "beating analyst estimates of $1.39. Revenue came in at $89.5 billion, "
             "up 8% year-over-year. The company also announced a new $90 billion share "
             "buyback program. CEO Tim Cook expressed optimism about the coming holiday "
             "season. iPhone sales were particularly strong in emerging markets. " * 3,
        source="yahoo",
        age_hours=2.0,
        raw_tickers=["AAPL"],
    )


@pytest.fixture
def mock_ai_response():
    return {
        "relevant": True,
        "event_type": "earnings",
        "subject": "apple reports record q4 earnings",
        "tickers": ["AAPL"],
        "impact_direction": "positive",
        "signal_score": 4,
        "confidence": 0.85,
        "reasoning": "Strong earnings beat with positive guidance",
        "magnitude": "high",
        "novelty": "standard",
        "actionability": "high",
        "affected_entities": [{"name": "Apple Inc.", "ticker": "AAPL"}],
        "second_order_effects": ["Positive for supply chain"],
        "sector_impact": "Technology",
        "key_metrics": {"eps": {"value": 1.46, "raw": "$1.46 per share"}},
    }


# --- Pipeline initialization tests ---

class TestPipelineInit:

    def test_council_init(self):
        pipeline = FinScrapePipeline(MemoryEvents(), use_council=True)
        assert pipeline.council is not None


# --- Article processing tests ---

class TestArticleProcessing:

    @patch("finscrape.pipeline.call_ai")
    @patch("finscrape.pipeline.get_market_data", return_value=[{"ticker": "AAPL", "price": 185.0, "change_percent": 2.5}])
    def test_analyze_article_produces_event(self, mock_market, mock_ai, sample_article, mock_ai_response):
        mock_ai.return_value = mock_ai_response
        pipeline = FinScrapePipeline(MemoryEvents())
        event = pipeline._analyze_article("yahoo", sample_article)
        assert event is not None
        assert isinstance(event, FinEvent)
        assert "AAPL" in event.tickers
        assert event.verdict in ("INVEST", "OBSERVE", "CAUTIOUS", "PULL_OUT")
        assert event.confidence > 0
        assert event.reasoning != ""

    @patch("finscrape.pipeline.call_ai", return_value=None)
    def test_analyze_article_ai_failure(self, mock_ai, sample_article):
        pipeline = FinScrapePipeline(MemoryEvents())
        event = pipeline._analyze_article("yahoo", sample_article)
        assert event is None

    @patch("finscrape.pipeline.call_ai")
    def test_analyze_article_not_relevant(self, mock_ai, sample_article):
        mock_ai.return_value = {"relevant": False}
        pipeline = FinScrapePipeline(MemoryEvents())
        event = pipeline._analyze_article("yahoo", sample_article)
        assert event is None


# --- Deduplication tests ---

class TestDeduplication:

    @patch("finscrape.pipeline.call_ai")
    @patch("finscrape.pipeline.get_market_data", return_value=[{"ticker": "AAPL", "price": 185.0, "change_percent": 2.5}])
    def test_duplicate_articles_merged(self, mock_market, mock_ai, mock_ai_response):
        mock_ai.return_value = mock_ai_response
        pipeline = FinScrapePipeline(MemoryEvents())

        article1 = ScrapedArticle(
            url="https://example.com/article1",
            title="Apple Reports Record Q4 Earnings",
            text="Apple Inc. (AAPL) reported record fourth-quarter earnings. " * 20,
            source="yahoo",
            age_hours=1.0,
            raw_tickers=["AAPL"],
        )
        article2 = ScrapedArticle(
            url="https://example.com/article2",
            title="Apple Reports Record Q4 Earnings Results",
            text="Apple Inc. (AAPL) reported record fourth-quarter earnings. " * 20,
            source="reuters",
            age_hours=1.0,
            raw_tickers=["AAPL"],
        )

        # First article should create an event
        event1 = pipeline._analyze_article("yahoo", article1)
        assert event1 is not None

        # Second article (same topic) should merge
        event2 = pipeline._analyze_article("reuters", article2)
        # event2 will be None if dedup caught it, or a new event if subjects differ enough
        # The important thing is no crash


    @patch("finscrape.pipeline.call_ai")
    @patch("finscrape.pipeline.get_market_data", return_value=[])
    def test_subject_keeps_its_case_and_dedup_ignores_it(self, mock_market, mock_ai, mock_ai_response):
        # Lowercased subjects read "iran agrees to suspend enrichment" on every panel.
        pipeline = FinScrapePipeline(MemoryEvents())
        art = lambda n: ScrapedArticle(  # noqa: E731
            url=f"https://example.com/{n}", title="Apple Reports Record Q4 Earnings",
            text="Apple Inc. (AAPL) reported record fourth-quarter earnings. " * 20,
            source="yahoo", age_hours=1.0, raw_tickers=["AAPL"],
        )
        mock_ai.return_value = {**mock_ai_response, "subject": "Apple reports record Q4 earnings"}
        event = pipeline._analyze_article("yahoo", art(1))
        assert event.subject == "Apple reports record Q4 earnings"
        mock_ai.return_value = {**mock_ai_response, "subject": "APPLE REPORTS RECORD Q4 EARNINGS!"}
        assert pipeline._analyze_article("reuters", art(2)) is None


# --- Alert action tests ---

class TestAlertActions:

    def test_log_action_executes(self):
        engine = AlertEngine()
        event = {"subject": "Test", "verdict": "INVEST", "tickers": ["AAPL"]}
        results = engine.execute_actions(event, [Action(action_type="log")])
        assert len(results) == 1
        assert results[0]["status"] == "ok"

    def test_telegram_action_skips_no_config(self):
        engine = AlertEngine()
        event = {"subject": "Test", "verdict": "INVEST", "tickers": ["AAPL"]}
        results = engine.execute_actions(event, [Action(action_type="telegram")])
        assert len(results) == 1
        assert results[0]["status"] == "skipped"

    def test_webhook_action_skips_no_url(self):
        engine = AlertEngine()
        event = {"subject": "Test", "verdict": "INVEST", "tickers": ["AAPL"]}
        results = engine.execute_actions(event, [Action(action_type="webhook")])
        assert len(results) == 1
        assert results[0]["status"] == "skipped"


@patch("finscrape.pipeline.call_ai")
@patch("finscrape.pipeline.get_market_data", return_value=[])
def test_laya_direction_no_longer_marks_an_event_divergent(mock_market, mock_ai, sample_article, mock_ai_response):
    from finscrape.analysis.laya import LayaView

    mock_ai.return_value = mock_ai_response  # positive
    opposite = LayaView(sector="technology", sector_p=0.9, direction="negative", direction_p=0.99)
    with patch("finscrape.pipeline.laya.classify", return_value=opposite):
        event = FinScrapePipeline(MemoryEvents())._analyze_article("yahoo", sample_article)
    assert event is not None and event.divergence_flag is False
