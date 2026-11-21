"""Deterministic fallback: event recognition, direction and sizing without an LLM."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from finscrape.analysis.fallback import analyze_without_llm
from finscrape.analysis.nlp import FinancialNLP
from finscrape.models import ScrapedArticle
from finscrape.pipeline import FinScrapePipeline


@pytest.fixture(scope="module")
def nlp() -> FinancialNLP:
    return FinancialNLP()


def call(title: str, text: str, nlp: FinancialNLP) -> dict | None:
    return analyze_without_llm(title, text, nlp.analyze(title, text))


def test_conflict_escalation_is_a_large_negative_call(nlp):
    result = call(
        "Iran closes Strait of Hormuz after missile strikes on tankers",
        "Iran closed the Strait of Hormuz after missile strikes on two tankers. "
        "Oil shipments were halted and crude prices rose 12%. Exxon Mobil warned "
        "of disruption. " * 2,
        nlp,
    )
    assert result is not None
    assert result["event_type"] == "geopolitical_event"
    assert result["impact_direction"] == "negative"
    assert result["signal_score"] <= -4
    assert result["magnitude"] == "high"
    assert result["actionability"] == "high"
    assert result["tickers"][0] == "XOM"
    assert result["key_metrics"]["analysis_source"] == "heuristic"
    assert result["key_metrics"]["fallback_event"] == "conflict_escalation"


def test_ceasefire_is_positive(nlp):
    result = call(
        "Israel and Hamas agree ceasefire after weeks of fighting",
        "Israel and Hamas agreed a ceasefire and prisoner exchange. Troops will "
        "withdraw from Gaza.",
        nlp,
    )
    assert result is not None
    assert result["impact_direction"] == "positive"
    assert result["signal_score"] >= 3
    assert "ceasefire" in result["key_metrics"]["fallback_event"]


def test_sanctions_are_negative_and_regulatory(nlp):
    result = call(
        "US imposes new sanctions on Iran shadow banking networks",
        "The United States imposed sanctions on Iranian banks and shadow banking "
        "networks, freezing assets.",
        nlp,
    )
    assert result is not None
    assert result["event_type"] == "regulatory_decision"
    assert result["impact_direction"] == "negative"
    assert result["signal_score"] <= -3
    assert result["sector_impact"] == "financials"


def test_tariffs_resolve_a_trade_proxy_when_no_company_is_named(nlp):
    result = call(
        "US imposes tariffs on Chinese imports",
        "The United States imposed new tariffs on Chinese imports, prompting retaliation.",
        nlp,
    )
    assert result is not None
    assert result["event_type"] == "regulatory_decision"
    assert result["signal_score"] < 0
    assert {"FXI", "SPY"} <= set(result["tickers"])


def test_hot_inflation_is_a_negative_macro_call(nlp):
    result = call(
        "Fed raises interest rates as inflation accelerates",
        "The Federal Reserve raised interest rates by 50 basis points, saying "
        "inflation accelerated. Stocks fell.",
        nlp,
    )
    assert result is not None
    assert result["event_type"] == "market_movement"
    assert result["impact_direction"] == "negative"
    assert result["signal_score"] <= -3


def test_earnings_beat_and_miss_take_the_right_direction(nlp):
    beat = call(
        "Oracle beats estimates and raises guidance on AI demand",
        "Oracle beat estimates and raised its guidance after revenue rose 18%. "
        "The company reported record profit.",
        nlp,
    )
    miss = call(
        "Oracle misses estimates and cuts guidance",
        "Oracle missed estimates and cut its guidance after revenue fell 8%.",
        nlp,
    )
    assert beat is not None and miss is not None
    assert beat["event_type"] == "earnings" and beat["signal_score"] >= 3
    assert miss["event_type"] == "earnings" and miss["signal_score"] <= -3
    assert beat["tickers"] == ["ORCL"]


def test_cyber_attack_is_negative_and_maps_security_tickers(nlp):
    result = call(
        "Company hacked in ransomware attack",
        "The company was hacked in a ransomware attack that breached customer data.",
        nlp,
    )
    assert result is not None
    assert result["impact_direction"] == "negative"
    assert result["signal_score"] < 0
    assert result["tickers"]


def test_opposing_events_are_reported_as_mixed(nlp):
    result = call(
        "Ceasefire collapses as airstrikes resume",
        "A ceasefire collapsed as airstrikes resumed across the border.",
        nlp,
    )
    assert result is not None
    assert result["impact_direction"] == "mixed"
    assert result["signal_score"] == 0


def test_uncertainty_lowers_actionability_and_confidence(nlp):
    certain = call(
        "US imposes sanctions on Iran", "The US imposed sanctions on Iran.", nlp
    )
    uncertain = call(
        "US reportedly plans to impose sanctions on Iran",
        "The US reportedly plans to impose sanctions on Iran, sources say.",
        nlp,
    )
    assert certain is not None and uncertain is not None
    assert uncertain["actionability"] == "low"
    assert uncertain["confidence"] < certain["confidence"]


def test_unrecognised_story_is_dropped_not_called_neutral(nlp):
    assert (
        call(
            "Local team wins regional football final", "A local football team won.", nlp
        )
        is None
    )


def test_recognised_event_without_a_named_company_uses_a_liquid_proxy(nlp):
    result = call(
        "Airstrikes hit a remote border area",
        "Airstrikes hit a remote border area.",
        nlp,
    )
    assert result is not None
    assert result["tickers"][:2] == ["ITA", "GLD"]


def test_numbers_lift_magnitude(nlp):
    plain = call("Company reports results", "The company reported results.", nlp)
    assert plain is None  # no event verb; nothing to score
    large = call(
        "Exxon Mobil agrees $20 billion acquisition",
        "Exxon Mobil agreed a $20 billion acquisition, its largest ever.",
        nlp,
    )
    assert large is not None
    assert large["magnitude"] == "high"
    assert large["signal_score"] >= 3


class _Store:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def add_event(self, event: dict) -> None:
        self.events.append(event)

    def update_event(self, *args, **kwargs) -> None:
        pass


def _article(title: str, text: str) -> ScrapedArticle:
    return ScrapedArticle(
        url="https://example.test/story",
        title=title,
        text=text,
        source="world/test:mainstream",
        age_hours=1.0,
    )


def test_pipeline_publishes_fallback_and_does_not_clamp_its_direction(monkeypatch):
    monkeypatch.setenv("FINSCRAPE_HEURISTIC_FALLBACK", "true")
    monkeypatch.setenv("FINSCRAPE_LAYA", "0")
    store = _Store()
    article = _article(
        "Iran closes Strait of Hormuz after missile strikes on tankers",
        "Iran closed the Strait of Hormuz after missile strikes on two tankers. "
        "Oil shipments were halted and crude prices rose 12%. Exxon Mobil warned "
        "of disruption. " * 2,
    )
    with patch("finscrape.pipeline.call_ai", lambda *a, **k: None):
        event = FinScrapePipeline(store)._analyze_article(
            "world/test:mainstream", article
        )
    assert event is not None
    assert event.verdict == "PULL_OUT"
    assert event.signal_score <= -4
    assert event.key_metrics["analysis_source"] == "heuristic"
    assert event.analysis_source == "heuristic", "the row says who judged it (m1.3.1)"
    assert event.model_name == ""
    assert (
        store.events and store.events[0]["key_metrics"]["prompt_variant"] == "heuristic"
    )


def test_pipeline_drops_the_story_when_fallback_is_disabled(monkeypatch):
    monkeypatch.delenv("FINSCRAPE_HEURISTIC_FALLBACK", raising=False)
    monkeypatch.setenv("FINSCRAPE_LAYA", "0")
    article = _article(
        "Oracle beats estimates and raises guidance",
        "Oracle beat estimates and raised its guidance after revenue rose 18%.",
    )
    with patch("finscrape.pipeline.call_ai", lambda *a, **k: None):
        event = FinScrapePipeline(_Store())._analyze_article(
            "world/test:mainstream", article
        )
    assert event is None


def test_every_rule_uses_a_validating_event_type_and_compiles():
    from finscrape.analysis.constants import VALID_EVENT_TYPES
    from finscrape.analysis.fallback import _RULES

    for rule in _RULES:
        assert rule.event_type in VALID_EVENT_TYPES
        assert rule.regex.search("") is None  # compiles


def test_fallback_works_without_spacy_by_using_empty_nlp_result():
    from finscrape.analysis.nlp import NLPResult

    result = analyze_without_llm(
        "Iran closes Strait of Hormuz",
        "Iran closed the Strait of Hormuz, halting oil shipments.",
        NLPResult(),
    )
    assert result is not None
    assert result["signal_score"] < 0
    assert result["tickers"]


def test_empty_text_is_not_a_market_call(nlp):
    assert call("", "", nlp) is None
