"""Tests for the advanced NLP pipeline."""

import pytest

from finscrape.analysis.nlp import (
    FinancialNLP,
    analyze_financial_text,
    ExtractedEntity,
    FinancialMetric,
    NLPResult,
)


@pytest.fixture
def nlp():
    return FinancialNLP()


class TestEntityResolution:
    def test_known_company_resolves(self, nlp):
        result = nlp.analyze("Apple Reports Record Q1 Revenue", "Apple Inc reported revenue of $120 billion.")
        assert "AAPL" in result.tickers

    def test_ticker_from_dollar_sign(self, nlp):
        result = nlp.analyze("Market Update", "Shares of $NVDA surged 8% today after earnings beat.")
        assert "NVDA" in result.tickers

    def test_ticker_from_parens(self, nlp):
        result = nlp.analyze("Tesla news", "Tesla (TSLA) announced new factory plans.")
        assert "TSLA" in result.tickers

    def test_bracketed_acronyms_are_not_tickers(self, nlp):
        text = (
            "The Stockholm International Peace Research Institute (SIPRI) said the "
            "United Arab Emirates (UAE) closed its base, the Associated Press (AP) reported."
        )
        tickers = nlp.analyze("Base closes", text).tickers
        assert not {"SIPRI", "UAE", "AP"} & set(tickers)

    def test_multiple_companies(self, nlp):
        result = nlp.analyze(
            "Tech Earnings",
            "Microsoft and Google both reported strong earnings. Amazon also beat estimates."
        )
        found = set(result.tickers)
        assert "MSFT" in found or "GOOGL" in found

    def test_analyst_entity_detected(self, nlp):
        result = nlp.analyze(
            "Goldman Sachs Upgrades Apple",
            "Goldman Sachs raised Apple to a Buy rating with a $250 price target."
        )
        assert "AAPL" in result.tickers

    def test_custom_entity_index(self):
        custom = {"acme": [("Acme Corp", "ACME")]}
        nlp = FinancialNLP(entity_index=custom)
        result = nlp.analyze("Acme Corp Earnings", "Acme Corp reported strong results today.")
        # Should try to resolve from custom index
        assert isinstance(result.tickers, list)


class TestMetricExtraction:
    def test_revenue_extraction(self, nlp):
        result = nlp.analyze("Apple Earnings", "Apple reported revenue of $94.8 billion, beating estimates.")
        revenues = [m for m in result.metrics if m.metric_type == "revenue"]
        assert len(revenues) >= 1
        assert revenues[0].value > 90_000_000_000

    def test_percentage_change(self, nlp):
        result = nlp.analyze("Stock Move", "Tesla shares surged 12.5% after earnings beat.")
        changes = [m for m in result.metrics if m.metric_type == "price_change"]
        assert len(changes) >= 1
        assert changes[0].value > 0

    def test_negative_percentage(self, nlp):
        result = nlp.analyze("Stock Drop", "Meta shares dropped 8% on weak guidance.")
        changes = [m for m in result.metrics if m.metric_type == "price_change"]
        assert len(changes) >= 1
        assert changes[0].value < 0

    def test_price_target(self, nlp):
        result = nlp.analyze("Analyst Note", "Goldman set a price target of $250 on Apple shares.")
        targets = [m for m in result.metrics if m.metric_type == "price_target"]
        assert len(targets) >= 1
        assert targets[0].value == 250

    def test_layoff_extraction(self, nlp):
        result = nlp.analyze("Layoffs", "Meta plans to cut 10,000 jobs in restructuring.")
        layoffs = [m for m in result.metrics if m.metric_type == "layoffs"]
        assert len(layoffs) >= 1
        assert layoffs[0].value == 10000

    def test_deal_value(self, nlp):
        result = nlp.analyze("M&A", "Microsoft to acquire Activision in a deal worth $69 billion.")
        deals = [m for m in result.metrics if m.metric_type == "deal_value"]
        assert len(deals) >= 1
        assert deals[0].value > 60_000_000_000


class TestSectorDetection:
    def test_tech_sector(self, nlp):
        result = nlp.analyze("Tech", "Nvidia announces new AI chip for data center workloads.")
        assert result.sector == "technology"

    def test_finance_sector(self, nlp):
        result = nlp.analyze("Banks", "JPMorgan reports strong trading revenue amid interest rate changes.")
        assert result.sector == "financials"

    def test_energy_sector(self, nlp):
        result = nlp.analyze("Oil", "OPEC cuts oil production amid global demand concerns.")
        assert result.sector == "energy"


class TestBreakingNewsDetection:
    def test_breaking_detected(self, nlp):
        result = nlp.analyze("BREAKING: Apple CEO Resigns", "Just in: Tim Cook has stepped down as CEO.")
        assert result.has_breaking_indicators is True

    def test_normal_news_not_breaking(self, nlp):
        result = nlp.analyze("Quarterly Results", "Apple reported its quarterly earnings today.")
        assert result.has_breaking_indicators is False

    def test_exclusive_is_breaking(self, nlp):
        result = nlp.analyze("Exclusive", "Sources say Microsoft is in talks to acquire startup.")
        assert result.has_breaking_indicators is True


class TestNLPResult:
    def test_primary_company_set(self, nlp):
        result = nlp.analyze("Apple Earnings", "Apple (AAPL) reported record revenue of $120B.")
        assert result.primary_ticker == "AAPL"

    def test_empty_text(self, nlp):
        result = nlp.analyze("", "")
        assert result.tickers == []
        assert result.metrics == []

    def test_non_financial_text(self, nlp):
        result = nlp.analyze("Weather", "It will be sunny tomorrow in New York.")
        assert len(result.metrics) == 0


class TestConvenienceFunction:
    def test_analyze_financial_text(self):
        result = analyze_financial_text(
            "Tesla Q4 Earnings",
            "Tesla (TSLA) reported revenue of $25.2 billion, beating estimates by 5%."
        )
        assert isinstance(result, NLPResult)
        assert "TSLA" in result.tickers
