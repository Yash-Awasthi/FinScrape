"""Tests for finscrape.market_data.compute_indicators and the GROUND TRUTH facts
pipeline: agents anchor their prompt to computed numbers, and reasoning that
states a conflicting number gets flagged on the verdict.

All LLM calls are stubbed. yfinance is never called — compute_indicators is
pure list math, and the agent/council tests feed market_facts in directly
instead of going through get_indicators.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

from finscrape.market_data import (
    clear_indicator_cache,
    compute_indicators,
    get_indicators,
)

# ---------------------------------------------------------------------------
# get_indicators — must fetch a real 52-week window, not a 6mo window wearing
# the 52-week label (compute_indicators takes max(closes) as the high water
# mark over whatever period it's handed).
# ---------------------------------------------------------------------------

class TestIndicatorFetchWindow:
    def test_fetches_1y_not_6mo(self):
        clear_indicator_cache()
        with patch("finscrape.market_data.yf.download") as mock_download:
            mock_download.return_value = MagicMock(empty=True)
            get_indicators(["AAPL"])
        assert mock_download.call_args.kwargs["period"] == "1y"


# ---------------------------------------------------------------------------
# compute_indicators — pure math over synthetic price lists
# ---------------------------------------------------------------------------

def _series(prices: list[float]) -> tuple[list[float], list[float], list[float]]:
    closes = list(prices)
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return closes, highs, lows


class TestComputeIndicators:
    def test_monotone_rising_series(self):
        closes, highs, lows = _series([100 + i for i in range(60)])
        result = compute_indicators(closes, highs, lows)
        assert result["rsi14"] == 100.0
        assert result["sma20"] > result["sma50"]

    def test_flat_series_rsi_neutral(self):
        closes, highs, lows = _series([100.0] * 60)
        result = compute_indicators(closes, highs, lows)
        assert result["rsi14"] == 50.0

    def test_short_series_returns_empty_dict_not_crash(self):
        closes, highs, lows = _series([100 + i for i in range(10)])
        assert compute_indicators(closes, highs, lows) == {}

    def test_mismatched_lengths_returns_empty_dict(self):
        closes, highs, lows = _series([100 + i for i in range(60)])
        assert compute_indicators(closes, highs[:-1], lows) == {}

    def test_falling_series_sma20_below_sma50(self):
        closes, highs, lows = _series([200 - i for i in range(60)])
        result = compute_indicators(closes, highs, lows)
        assert result["rsi14"] == 0.0
        assert result["sma20"] < result["sma50"]


# ---------------------------------------------------------------------------
# Stub finscrape.analysis.ai_client so importing the agents package never
# needs requests/dotenv, matching the pattern in tests/test_agents.py.
# ---------------------------------------------------------------------------
_ai_client_mod = types.ModuleType("finscrape.analysis.ai_client")
_ai_client_mod.call_ai = MagicMock(return_value=None)
sys.modules["finscrape.analysis.ai_client"] = _ai_client_mod

from finscrape.agents.base import BaseAgent
from finscrape.agents.council import AgentCouncil
from finscrape.analysis.validator import check_number_conflicts

del sys.modules["finscrape.analysis.ai_client"]


class _StubAgent(BaseAgent):
    """Minimal concrete agent — goes through the real analyze()/_run() path
    so call_ai() actually gets invoked with the built prompt."""

    def __init__(self, agent_name: str = "stub", weight: float = 1.0):
        super().__init__(weight=weight)
        self._name = agent_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> str:
        return "Stub test agent"

    @property
    def system_prompt(self) -> str:
        return "You are a test agent."


def _fixed_response(reasoning: str) -> dict:
    return {
        "verdict": "INVEST",
        "signal_score": 4,
        "confidence": 0.8,
        "reasoning": reasoning,
        "tickers": ["AAPL"],
        "risk_factors": [],
        "key_insights": [],
    }


# ---------------------------------------------------------------------------
# GROUND TRUTH block reaches the agent prompt
# ---------------------------------------------------------------------------

class TestMarketFactsInPrompt:
    def test_market_facts_render_into_agent_prompt(self):
        captured = {}

        def fake_call_ai(prompt, system_prompt, model=None):
            captured["prompt"] = prompt
            return _fixed_response("Momentum looks healthy here.")

        council = AgentCouncil(agents=[_StubAgent()])
        with patch("finscrape.agents.base.call_ai", side_effect=fake_call_ai):
            council.deliberate(
                "Apple headline", "Apple body text.",
                market_facts={"AAPL": {"rsi14": 31.2}},
            )

        assert "31.2" in captured["prompt"]
        assert "never invent your own" in captured["prompt"]


# ---------------------------------------------------------------------------
# check_number_conflicts — deterministic anti-hallucination
# ---------------------------------------------------------------------------

class TestCheckNumberConflicts:
    def test_conflicting_number_detected(self):
        conflicts = check_number_conflicts("RSI is 82 and climbing.", {"rsi14": 31.2})
        assert conflicts

    def test_matching_number_no_conflict(self):
        conflicts = check_number_conflicts("RSI is 31.2 and climbing.", {"rsi14": 31.2})
        assert conflicts == []

    def test_no_facts_no_conflict(self):
        assert check_number_conflicts("RSI is 82.", {}) == []

    def test_unrelated_reasoning_no_conflict(self):
        conflicts = check_number_conflicts("Strong momentum, no red flags.", {"rsi14": 31.2})
        assert conflicts == []


class TestNumberConflictFlag:
    def test_flag_lands_on_verdict(self):
        def fake_call_ai(prompt, system_prompt, model=None):
            return _fixed_response("RSI is 82, deeply overbought, but I like it anyway.")

        council = AgentCouncil(agents=[_StubAgent()])
        with patch("finscrape.agents.base.call_ai", side_effect=fake_call_ai):
            cv = council.deliberate(
                "Apple headline", "Apple body.",
                market_facts={"AAPL": {"rsi14": 31.2}},
            )

        assert cv.individual_verdicts[0].number_conflict is True

    def test_no_flag_when_reasoning_matches_facts(self):
        def fake_call_ai(prompt, system_prompt, model=None):
            return _fixed_response("RSI is 31.2, nothing extreme here.")

        council = AgentCouncil(agents=[_StubAgent()])
        with patch("finscrape.agents.base.call_ai", side_effect=fake_call_ai):
            cv = council.deliberate(
                "Apple headline", "Apple body.",
                market_facts={"AAPL": {"rsi14": 31.2}},
            )

        assert cv.individual_verdicts[0].number_conflict is False

    def test_conflict_discounts_consensus_confidence(self):
        def clean_call_ai(prompt, system_prompt, model=None):
            return _fixed_response("RSI is 31.2, healthy.")

        def conflict_call_ai(prompt, system_prompt, model=None):
            return _fixed_response("RSI is 82, overbought.")

        facts = {"AAPL": {"rsi14": 31.2}}

        with patch("finscrape.agents.base.call_ai", side_effect=clean_call_ai):
            baseline = AgentCouncil(agents=[_StubAgent("clean")]).deliberate(
                "H", "B", market_facts=facts
            )

        with patch("finscrape.agents.base.call_ai", side_effect=conflict_call_ai):
            flagged = AgentCouncil(agents=[_StubAgent("conflict")]).deliberate(
                "H", "B", market_facts=facts
            )

        assert flagged.consensus_confidence < baseline.consensus_confidence
