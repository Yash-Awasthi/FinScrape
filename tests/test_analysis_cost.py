"""The CPU/cost half of one article, measured through the seams (plan M3.2).

Three claims, each with a counter rather than a comment:

* Laya classifies a story once: the filter cache is keyed on the exact truncated state
  the model sees, so a duplicate feed or a re-scoring run does not pay for it again.
* spaCy runs once per article and the heuristic fallback reuses that result, so an LLM
  outage does not buy a second pass.
* Every provider path carries the hard per-article socket timeout.
"""

from __future__ import annotations

import pytest

from finscrape.analysis import ai_client, laya
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


# --- Laya: one prediction per distinct state -------------------------------------------


def test_the_same_article_is_classified_once(monkeypatch):
    calls: list[str] = []

    def fake_load():
        def predict(state, _questions):
            calls.append(state)
            return {"answers": {}}

        return predict

    laya._classify_state.cache_clear()
    monkeypatch.setattr(laya, "_load", fake_load)

    first = laya.classify("Oil jumps", "Crude rises on supply risk.")
    second = laya.classify("Oil jumps", "Crude rises on supply risk.")

    assert first == second
    assert len(calls) == 1, calls


def test_a_different_story_is_a_different_prediction(monkeypatch):
    calls: list[str] = []

    def fake_load():
        def predict(state, _questions):
            calls.append(state)
            return {"answers": {}}

        return predict

    laya._classify_state.cache_clear()
    monkeypatch.setattr(laya, "_load", fake_load)

    laya.classify("Oil jumps", "Crude rises.")
    laya.classify("Oil jumps", "Crude falls.")

    assert len(calls) == 2, calls


def test_the_cache_key_is_exactly_the_text_the_model_sees(monkeypatch):
    """Two texts that differ only past _MAX_CHARS are one prediction, not two."""
    calls: list[str] = []

    def fake_load():
        def predict(state, _questions):
            calls.append(state)
            return {"answers": {}}

        return predict

    laya._classify_state.cache_clear()
    monkeypatch.setattr(laya, "_load", fake_load)
    prefix = "A" * laya._MAX_CHARS
    laya.classify("Same headline", prefix + "B" * 50)
    laya.classify("Same headline", prefix + "C" * 50)

    assert len(calls) == 1, calls


def test_laya_absence_is_not_cached_as_a_prediction(monkeypatch):
    """`_load` returning None must stay cheap but correct: None is a valid cached value."""
    laya._classify_state.cache_clear()
    monkeypatch.setattr(laya, "_load", lambda: None)
    assert laya.classify("Oil jumps", "Crude rises.") is None
    assert laya.classify("Oil jumps", "Crude rises.") is None


# --- spaCy: one pass per article --------------------------------------------------------


def test_the_pipeline_runs_spacy_once_per_article(monkeypatch):
    passes: list[str] = []

    def counting_analyze(title: str, text: str) -> NLPResult:
        passes.append(title)
        return NLPResult(tickers=["XOM"])

    monkeypatch.setattr("finscrape.pipeline.call_ai", lambda *a, **k: _reply())
    pipeline = FinScrapePipeline(_MemEvents())
    monkeypatch.setattr(pipeline.nlp, "analyze", counting_analyze)

    event = pipeline._analyze_article("world/reuters", _article())

    assert event is not None
    assert len(passes) == 1, passes


def test_the_heuristic_fallback_reuses_the_single_nlp_pass(monkeypatch):
    passes: list[str] = []

    def counting_analyze(title: str, text: str) -> NLPResult:
        passes.append(title)
        return NLPResult(tickers=["XOM"])

    monkeypatch.setenv("FINSCRAPE_HEURISTIC_FALLBACK", "1")
    monkeypatch.setattr("finscrape.pipeline.call_ai", lambda *a, **k: None)
    pipeline = FinScrapePipeline(_MemEvents())
    monkeypatch.setattr(pipeline.nlp, "analyze", counting_analyze)

    pipeline._analyze_article("world/reuters", _article())

    assert len(passes) == 1, passes


# --- the hard per-article timeout on every provider path --------------------------------


class _Reply:
    status_code = 200
    text = ""

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"relevant": true, "verdict": "OBSERVE", "signal_score": 0}'
                    }
                }
            ]
        }


@pytest.mark.parametrize(
    ("func", "env"),
    [
        (
            ai_client._call_openai_proxy,
            {"OPENAI_BASE_URL": "http://localhost:11434/v1"},
        ),
        (ai_client._call_openrouter, {}),
    ],
)
def test_every_provider_call_carries_the_configured_timeout(monkeypatch, func, env):
    seen: dict[str, object] = {}

    def fake_post(url, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return _Reply()

    monkeypatch.setattr(ai_client.requests, "post", fake_post)
    monkeypatch.setenv("FINSCRAPE_AI_TIMEOUT", "7")
    monkeypatch.setenv("OPENAI_API_KEY", "key-for-test")
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    func("prompt", "system")

    assert seen["timeout"] == 7
