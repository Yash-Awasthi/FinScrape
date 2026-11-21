"""Production makes exactly one LLM call per article (plan M1.7).

The product claims one model judgment plus deterministic layers. The council mode issues
eight calls per article plus an optional judge, so it must be unreachable in production —
this file proves that with a counter on the real `call_ai` seam, and proves the council
route 404s by default.
"""

from __future__ import annotations

import pytest

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
        "tickers": ["XOM", "CVX"],
        "magnitude": "medium",
        "novelty": "standard",
        "actionability": "high",
        "affected_entities": [{"name": "Exxon Mobil", "ticker": "XOM"}],
        "second_order_effects": ["Tanker rates rise"],
        "key_metrics": {},
    }


def test_a_default_run_makes_exactly_one_model_call(monkeypatch):
    calls: list[str] = []

    def counting_call_ai(prompt, system_prompt=None, **_):
        calls.append(prompt[:40])
        return _reply()

    monkeypatch.setattr("finscrape.pipeline.call_ai", counting_call_ai)
    pipeline = FinScrapePipeline(_MemEvents())
    event = pipeline._analyze_article("world/reuters", _article())
    assert event is not None
    assert len(calls) == 1, calls
    # The deterministic layers post-process that one reply; they never call out.
    assert "XOM" in event.tickers


def test_the_laya_and_nlp_layers_do_not_reach_the_model(monkeypatch):
    """Sector/direction (Laya) and NLP are local models: they must not become calls."""

    def boom(*a, **kw):  # any second LLM call, from any layer, fails the test
        raise AssertionError("a second model call went out")

    replies = [_reply()]

    def one_call_then_forbid(prompt, system_prompt=None, **_):
        if replies:
            return replies.pop()
        return boom()

    monkeypatch.setattr("finscrape.pipeline.call_ai", one_call_then_forbid)
    # Force the sector classifier down its fallback path too: the heuristic map is local.
    monkeypatch.setenv("FINSCRAPE_LAYA", "0")
    pipeline = FinScrapePipeline(_MemEvents())
    assert pipeline._analyze_article("world/reuters", _article()) is not None


def test_the_council_mode_is_refused_in_production(monkeypatch):
    monkeypatch.setenv("WORLDFIN_ENV", "production")
    with pytest.raises(RuntimeError, match="offline/experimental"):
        FinScrapePipeline(_MemEvents(), use_council=True)
    monkeypatch.delenv("WORLDFIN_ENV")


def test_production_paths_never_ask_for_the_council():
    """Neither entry point passes `use_council`, so the default is the only one used."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for path in ("worker/runner.py", "scripts/reanalyse.py"):
        source = (root / path).read_text(encoding="utf-8")
        assert "FinScrapePipeline(" in source, path
        assert "use_council=True" not in source, path


def test_the_council_route_404s_by_default(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.routes import ai as ai_routes
    from server.settings import get_settings

    monkeypatch.delenv("WORLDFIN_ENABLE_COUNCIL", raising=False)
    monkeypatch.delenv("WORLDFIN_ENV", raising=False)
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(ai_routes.router)
    resp = TestClient(app).get("/api/ai/council?id=1")
    assert resp.status_code == 404 and resp.json()["detail"] == "council disabled"


def test_the_council_route_stays_404_in_production_even_when_enabled(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.routes import ai as ai_routes
    from server.settings import get_settings

    monkeypatch.setenv("WORLDFIN_ENABLE_COUNCIL", "1")
    monkeypatch.setenv("WORLDFIN_ENV", "production")
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(ai_routes.router)
    resp = TestClient(app).get("/api/ai/council?id=1")
    assert resp.status_code == 404
    monkeypatch.delenv("WORLDFIN_ENV")
    monkeypatch.delenv("WORLDFIN_ENABLE_COUNCIL")
    get_settings.cache_clear()
