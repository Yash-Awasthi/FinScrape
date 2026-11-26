"""The daily token ceiling blocks model calls and labels the heuristic downgrade."""

from __future__ import annotations

import json

import pytest

from finscrape.analysis import ai_client, budget
from finscrape.analysis.nlp import NLPResult
from finscrape.models import ScrapedArticle
from finscrape.pipeline import FinScrapePipeline


@pytest.fixture(autouse=True)
def _budget_state(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSCRAPE_BUDGET_STATE", str(tmp_path / "budget.json"))
    monkeypatch.setenv("FINSCRAPE_DAILY_TOKEN_CEILING", "100")
    monkeypatch.setenv("FINSCRAPE_OUTPUT_TOKEN_RESERVE", "10")
    ai_client.begin_analysis()
    ai_client.clear_cache()


def test_reserve_stops_at_the_ceiling_and_settle_refunds(monkeypatch):
    assert budget.reserve(60) is True
    assert budget.reserve(50) is False
    assert budget.used() == 60
    budget.settle(60, 30)
    assert budget.used() == 30
    assert budget.reserve(70) is True


def test_a_zero_ceiling_disables_the_guard(monkeypatch):
    monkeypatch.setenv("FINSCRAPE_DAILY_TOKEN_CEILING", "0")
    assert budget.reserve(10_000_000) is True
    assert budget.used() == 0


def test_a_new_utc_day_starts_from_zero(tmp_path):
    state = tmp_path / "budget.json"
    state.write_text(json.dumps({"date": "2000-01-01", "tokens": 99}), encoding="utf-8")
    assert budget.used() == 0


def _reply() -> dict:
    return {"relevant": True, "verdict": "OBSERVE", "signal_score": 0}


def test_the_guard_blocks_the_dispatch_and_flags_the_article(monkeypatch):
    sent: list[str] = []

    def fake_dispatch(prompt, system_prompt, model):
        sent.append(prompt)
        return _reply()

    monkeypatch.setattr(ai_client, "_dispatch", fake_dispatch)
    monkeypatch.setenv("FINSCRAPE_MODEL_FALLBACK", "")
    monkeypatch.setenv("FINSCRAPE_DAILY_TOKEN_CEILING", "5")

    assert ai_client.call_ai("a prompt", "a system") is None
    assert sent == []
    assert ai_client.budget_blocked() is True
    assert budget.used() == 0


def test_a_call_under_the_ceiling_proceeds_and_is_charged(monkeypatch):
    sent: list[str] = []

    def fake_dispatch(prompt, system_prompt, model):
        sent.append(prompt)
        return _reply()

    monkeypatch.setattr(ai_client, "_dispatch", fake_dispatch)
    monkeypatch.setenv("FINSCRAPE_DAILY_TOKEN_CEILING", "100000")

    result = ai_client.call_ai("a prompt", "a system")

    assert result is not None
    assert sent == ["a prompt"]
    assert ai_client.budget_blocked() is False
    assert budget.used() > 0


# --- pipeline downgrade --------------------------------------------------------------


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


def test_a_budget_block_downgrades_even_when_the_fallback_flag_is_off(monkeypatch):
    monkeypatch.delenv("FINSCRAPE_HEURISTIC_FALLBACK", raising=False)
    monkeypatch.setattr("finscrape.pipeline.call_ai", lambda *a, **k: None)
    monkeypatch.setattr("finscrape.pipeline.budget_blocked", lambda: True)
    pipeline = FinScrapePipeline(_MemEvents())
    monkeypatch.setattr(
        pipeline.nlp, "analyze", lambda title, text: NLPResult(tickers=["XOM"])
    )

    event = pipeline._analyze_article("world/reuters", _article())

    assert event is not None
    assert event.analysis_source == "heuristic"
    assert event.key_metrics["fallback_reason"] == "daily_token_ceiling"


def test_without_the_budget_the_opt_in_is_still_required(monkeypatch):
    monkeypatch.delenv("FINSCRAPE_HEURISTIC_FALLBACK", raising=False)
    monkeypatch.setattr("finscrape.pipeline.call_ai", lambda *a, **k: None)
    monkeypatch.setattr("finscrape.pipeline.budget_blocked", lambda: False)
    pipeline = FinScrapePipeline(_MemEvents())
    monkeypatch.setattr(
        pipeline.nlp, "analyze", lambda title, text: NLPResult(tickers=["XOM"])
    )

    assert pipeline._analyze_article("world/reuters", _article()) is None
    assert pipeline.ai_failed() is True
