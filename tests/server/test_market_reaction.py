"""One-day money-flow confirmation: price move plus abnormal volume."""

from __future__ import annotations

import pandas as pd
import pytest

from finscrape import market_data
from finscrape.analysis.market_reaction import apply_market_confirmation
from finscrape.models import ScrapedArticle
from finscrape.pipeline import FinScrapePipeline


def test_extreme_aligned_move_lifts_score_and_quality():
    result = apply_market_confirmation(
        +2,
        "positive",
        {"NVDA": {"ticker": "NVDA", "change_percent": 31.5, "volume_ratio": 3.0}},
    )
    assert result.delta == 2
    assert result.magnitude == "high"
    assert result.actionability == "high"
    assert result.confidence > 0
    assert "NVDA" in result.evidence


def test_direction_is_symmetric_for_negative_events():
    result = apply_market_confirmation(
        -2,
        "negative",
        {"XOM": {"ticker": "XOM", "change_percent": -18.0, "volume_ratio": 2.0}},
    )
    assert result.delta == 2
    assert result.magnitude == "high"


def test_strong_move_needs_participation_for_one_point():
    strong = apply_market_confirmation(
        +2, "positive", {"X": {"change_percent": 8.0, "volume_ratio": 1.3}}
    )
    thin = apply_market_confirmation(
        +2, "positive", {"X": {"change_percent": 20.0, "volume_ratio": 1.0}}
    )
    assert strong.delta == 1
    assert thin.delta == 0


def test_opposing_spike_lowers_confidence_without_flipping_the_call():
    result = apply_market_confirmation(
        +2,
        "positive",
        {"NVDA": {"ticker": "NVDA", "change_percent": -20.0, "volume_ratio": 2.0}},
    )
    assert result.delta == 0
    assert result.confidence < 0
    assert "against" in result.evidence


def test_no_call_or_no_data_stays_neutral():
    assert (
        apply_market_confirmation(
            0, "neutral", {"X": {"change_percent": 40.0, "volume_ratio": 3.0}}
        ).delta
        == 0
    )
    assert apply_market_confirmation(2, "positive", {}).delta == 0


def _frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=25, freq="D")
    closes = [100.0 + (0.5 if i % 2 else 0.0) for i in range(24)] + [135.0]
    volumes = [1_000_000.0] * 24 + [3_000_000.0]
    high = [101.0] * 24 + [136.0]
    low = [99.0] * 24 + [104.0]
    return pd.DataFrame(
        {
            ("NVDA", "Close"): closes,
            ("NVDA", "High"): high,
            ("NVDA", "Low"): low,
            ("NVDA", "Volume"): volumes,
        },
        index=index,
    )


def test_fetch_reaction_reads_price_volume_and_flow(monkeypatch):
    monkeypatch.setattr(market_data.yf, "download", lambda *a, **k: _frame())
    market_data.clear_reaction_cache()
    row = market_data.get_market_reaction(["NVDA"])["NVDA"]
    assert row["change_percent"] == pytest.approx(34.33, abs=0.02)
    assert row["volume_ratio"] == 3.0
    assert row["dollar_volume_ratio"] > 3.0
    assert row["money_flow_ratio"] > 0
    assert row["range_percent"] > 0


class _Store:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def add_event(self, event: dict) -> None:
        self.events.append(event)

    def update_event(self, *args, **kwargs) -> None:
        pass


def _article() -> ScrapedArticle:
    return ScrapedArticle(
        url="https://example.test/nvda",
        title="Nvidia raises guidance after record AI demand",
        text="Nvidia raised guidance after record AI demand. Nvidia shares rose.",
        source="world/test:market",
        age_hours=0.5,
    )


def _result() -> dict:
    return {
        "relevant": True,
        "event_type": "guidance",
        "subject": "Nvidia raises guidance",
        "impact_direction": "positive",
        "tickers": ["NVDA"],
        "affected_entities": [
            {
                "name": "NVIDIA CORP",
                "ticker": "NVDA",
                "role": "primary",
                "impact": "positive",
            }
        ],
        "signal_score": 2,
        "confidence": 0.5,
        "magnitude": "medium",
        "novelty": "standard",
        "actionability": "low",
        "reasoning": "test",
        "key_metrics": {},
        "sector_impact": "technology",
        "second_order_effects": [],
    }


def test_pipeline_adds_market_confirmation_and_records_evidence(monkeypatch):
    monkeypatch.setenv("FINSCRAPE_LAYA", "0")
    monkeypatch.setattr("finscrape.pipeline.call_ai", lambda *a, **k: _result())
    monkeypatch.setattr(
        "finscrape.pipeline.get_market_reaction",
        lambda symbols: {
            "NVDA": {
                "ticker": "NVDA",
                "price": 165.0,
                "change_percent": 31.5,
                "volume_ratio": 3.0,
                "dollar_volume_ratio": 4.0,
            }
        },
    )
    store = _Store()
    event = FinScrapePipeline(store)._analyze_article("world/test:market", _article())
    assert event is not None
    assert event.signal_score == 4
    assert event.magnitude == "high"
    assert event.actionability == "high"
    assert event.key_metrics["market_confirmation"]
    assert event.key_metrics["market_reaction"][0]["ticker"] == "NVDA"
    assert store.events


def test_pipeline_does_not_flip_on_an_opposing_spike(monkeypatch):
    monkeypatch.setenv("FINSCRAPE_LAYA", "0")
    monkeypatch.setattr("finscrape.pipeline.call_ai", lambda *a, **k: _result())
    monkeypatch.setattr(
        "finscrape.pipeline.get_market_reaction",
        lambda symbols: {
            "NVDA": {"ticker": "NVDA", "change_percent": -20.0, "volume_ratio": 2.0}
        },
    )
    event = FinScrapePipeline(_Store())._analyze_article(
        "world/test:market", _article()
    )
    assert event is not None
    assert event.signal_score == 2
    assert "against" in event.key_metrics["market_confirmation"]
