"""The daily token ceiling, end to end through the real call_ai and the real pipeline.

The unit proof is `tests/server/test_budget_guard.py`; this file proves the same guard on
the shipped path: the reservation, the dispatch refusal and the pipeline downgrade. Only
the network boundary is faked, never `finscrape.pipeline.call_ai`.
"""

from __future__ import annotations

import pytest

from finscrape.analysis import ai_client, budget
from finscrape.analysis.nlp import NLPResult
from finscrape.models import ScrapedArticle
from finscrape.pipeline import FinScrapePipeline


class _MemEvents:
    @property
    def events(self) -> list[dict]:
        return []

    def add_event(self, event: dict) -> int:
        return 1

    def update_event(self, event_id: int, **kwargs: object) -> None:
        return None


def _article() -> ScrapedArticle:
    return ScrapedArticle(
        url="https://example.com/hormuz",
        title="Oil jumps as Hormuz shipping halts",
        text=(
            "Crude oil futures rose after shipping through the Strait of Hormuz halted. "
            "Exxon Mobil (XOM) and Chevron (CVX) gained as tanker rates spiked. "
        )
        * 4,
        source="world/reuters",
        age_hours=1.0,
        raw_tickers=["XOM"],
    )


def _reply() -> dict:
    return {
        "relevant": True,
        "verdict": "INVEST",
        "signal_score": 2,
        "confidence": 0.7,
        "reasoning": "Supply risk lifts energy names.",
        "sector_impact": "Energy",
        "tickers": ["XOM"],
        "magnitude": "medium",
        "novelty": "standard",
        "actionability": "high",
        "affected_entities": [{"name": "Exxon Mobil", "ticker": "XOM"}],
        "second_order_effects": [],
        "key_metrics": {},
    }


@pytest.fixture(autouse=True)
def _budget_state(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSCRAPE_BUDGET_STATE", str(tmp_path / "budget.json"))
    monkeypatch.setenv("FINSCRAPE_DAILY_TOKEN_CEILING", "10")
    monkeypatch.setenv("FINSCRAPE_OUTPUT_TOKEN_RESERVE", "10")
    monkeypatch.setenv("FINSCRAPE_MODEL_FALLBACK", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-key-for-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.delenv("FINSCRAPE_HEURISTIC_FALLBACK", raising=False)
    ai_client.begin_analysis()
    ai_client.clear_cache()


def test_an_exhausted_ceiling_refuses_the_call_before_the_backend(monkeypatch):
    sent: list[str] = []

    def fake_dispatch(prompt, system_prompt, model):
        sent.append(prompt)
        return _reply()

    monkeypatch.setattr(ai_client, "_call_openrouter", fake_dispatch)

    assert ai_client.call_ai("a prompt", "a system") is None
    assert sent == []
    assert ai_client.budget_blocked() is True
    assert budget.used() == 0


def test_the_real_pipeline_downgrades_when_the_ceiling_is_spent(monkeypatch):
    sent: list[str] = []

    def fake_dispatch(prompt, system_prompt, model):
        sent.append(prompt)
        return _reply()

    monkeypatch.setattr(ai_client, "_call_openrouter", fake_dispatch)
    pipeline = FinScrapePipeline(_MemEvents())
    monkeypatch.setattr(
        pipeline.nlp, "analyze", lambda title, text: NLPResult(tickers=["XOM"])
    )

    event = pipeline._analyze_article("world/reuters", _article())

    assert sent == []
    assert event is not None
    assert event.analysis_source == "heuristic"
    assert event.key_metrics["fallback_reason"] == "daily_token_ceiling"


def test_a_large_ceiling_lets_the_same_path_reach_the_backend(monkeypatch):
    monkeypatch.setenv("FINSCRAPE_DAILY_TOKEN_CEILING", "100000")
    sent: list[str] = []

    def fake_dispatch(prompt, system_prompt, model):
        sent.append(prompt)
        return _reply()

    monkeypatch.setattr(ai_client, "_call_openrouter", fake_dispatch)

    result = ai_client.call_ai("a prompt", "a system")

    assert sent == ["a prompt"]
    assert result is not None
    assert result["analysis_source"] == "model"
    assert budget.used() > 0
