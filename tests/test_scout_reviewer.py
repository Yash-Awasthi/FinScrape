"""
Tests for the ScoutAgent and ReviewerAgent personas.

All tests use mocked AI responses — no actual API calls are made.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub out finscrape.analysis.ai_client so we never import requests/dotenv
# at module level.
# ---------------------------------------------------------------------------
_ai_client_mod = types.ModuleType("finscrape.analysis.ai_client")
_ai_client_mod.call_ai = MagicMock(return_value=None)
sys.modules.setdefault("finscrape.analysis.ai_client", _ai_client_mod)

from finscrape.agents import ReviewerAgent as ExportedReviewer
from finscrape.agents import ScoutAgent as ExportedScout
from finscrape.agents.council import AgentCouncil
from finscrape.agents.personas import (
    DEFAULT_AGENTS,
    ReviewerAgent,
    ScoutAgent,
)

# ===================================================================
# ScoutAgent tests
# ===================================================================

class TestScoutAgent:

    def test_name(self):
        agent = ScoutAgent()
        assert agent.name == "scout"

    def test_default_weight(self):
        agent = ScoutAgent(weight=0.7)
        assert agent.weight == 0.7

    def test_role_is_non_empty(self):
        agent = ScoutAgent()
        assert len(agent.role) > 10

    def test_system_prompt_contains_source_quality(self):
        agent = ScoutAgent()
        prompt = agent.system_prompt.lower()
        assert "source" in prompt
        assert "quality" in prompt or "credib" in prompt

    def test_system_prompt_contains_novelty(self):
        agent = ScoutAgent()
        prompt = agent.system_prompt.lower()
        assert "novelty" in prompt or "novel" in prompt

    def test_system_prompt_contains_timeliness(self):
        agent = ScoutAgent()
        prompt = agent.system_prompt.lower()
        assert "timeli" in prompt or "fresh" in prompt

    def test_system_prompt_contains_headline_accuracy(self):
        agent = ScoutAgent()
        prompt = agent.system_prompt.lower()
        assert "headline" in prompt
        assert "clickbait" in prompt or "sensational" in prompt

    def test_system_prompt_returns_json(self):
        agent = ScoutAgent()
        assert "json" in agent.system_prompt.lower()

    def test_analyze_with_mocked_ai(self):
        mock_response = {
            "verdict": "OBSERVE",
            "signal_score": 2,
            "confidence": 0.7,
            "reasoning": "Credible source, moderately novel.",
            "tickers": ["MSFT"],
            "risk_factors": [],
            "key_insights": ["New information from primary source"],
        }
        with patch("finscrape.agents.base.call_ai", return_value=mock_response):
            agent = ScoutAgent(weight=0.7)
            result = agent.analyze("Microsoft Acquires Startup", "Microsoft announced...")
            assert result.agent_name == "scout"
            assert result.signal_score == 2
            assert result.verdict == "OBSERVE"


# ===================================================================
# ReviewerAgent tests
# ===================================================================

class TestReviewerAgent:

    def test_name(self):
        agent = ReviewerAgent()
        assert agent.name == "reviewer"

    def test_default_weight(self):
        agent = ReviewerAgent(weight=1.4)
        assert agent.weight == 1.4

    def test_role_is_non_empty(self):
        agent = ReviewerAgent()
        assert len(agent.role) > 10

    def test_system_prompt_contains_claim_verifiability(self):
        agent = ReviewerAgent()
        prompt = agent.system_prompt.lower()
        assert "verif" in prompt  # verifiable, verify, verifiability
        assert "claim" in prompt

    def test_system_prompt_contains_completeness(self):
        agent = ReviewerAgent()
        prompt = agent.system_prompt.lower()
        assert "complete" in prompt

    def test_system_prompt_contains_market_pricing(self):
        agent = ReviewerAgent()
        prompt = agent.system_prompt.lower()
        assert "priced" in prompt or "pricing" in prompt

    def test_system_prompt_contains_consistency(self):
        agent = ReviewerAgent()
        prompt = agent.system_prompt.lower()
        assert "inconsisten" in prompt or "consisten" in prompt

    def test_system_prompt_returns_json(self):
        agent = ReviewerAgent()
        assert "json" in agent.system_prompt.lower()

    def test_analyze_with_mocked_ai(self):
        mock_response = {
            "verdict": "CAUTIOUS",
            "signal_score": -1,
            "confidence": 0.65,
            "reasoning": "Key claims are unverifiable, missing context.",
            "tickers": ["TSLA"],
            "risk_factors": ["Unverifiable revenue claims"],
            "key_insights": [],
        }
        with patch("finscrape.agents.base.call_ai", return_value=mock_response):
            agent = ReviewerAgent(weight=1.4)
            result = agent.analyze("Tesla Expansion Plans", "Tesla is rumored to...")
            assert result.agent_name == "reviewer"
            assert result.signal_score == -1
            assert result.verdict == "CAUTIOUS"


# ===================================================================
# DEFAULT_AGENTS list tests
# ===================================================================

class TestDefaultAgents:

    def test_default_agents_has_seven_members(self):
        assert len(DEFAULT_AGENTS) == 8

    def test_scout_in_default_agents(self):
        names = [a.name for a in DEFAULT_AGENTS]
        assert "scout" in names

    def test_reviewer_in_default_agents(self):
        names = [a.name for a in DEFAULT_AGENTS]
        assert "reviewer" in names

    def test_scout_weight_in_defaults(self):
        scout = next(a for a in DEFAULT_AGENTS if a.name == "scout")
        assert scout.weight == 0.7

    def test_reviewer_weight_in_defaults(self):
        reviewer = next(a for a in DEFAULT_AGENTS if a.name == "reviewer")
        assert reviewer.weight == 1.4

    def test_all_agent_names_unique(self):
        names = [a.name for a in DEFAULT_AGENTS]
        assert len(names) == len(set(names))

    def test_all_agents_have_positive_weights(self):
        for agent in DEFAULT_AGENTS:
            assert agent.weight > 0, f"{agent.name} has non-positive weight"


# ===================================================================
# Export tests
# ===================================================================

class TestExports:

    def test_scout_exported_from_init(self):
        assert ExportedScout is ScoutAgent

    def test_reviewer_exported_from_init(self):
        assert ExportedReviewer is ReviewerAgent


# ===================================================================
# Council integration with new agents (mocked)
# ===================================================================

class TestCouncilWithNewAgents:

    def test_council_deliberation_with_all_seven(self):
        """Run the full 7-agent council with mocked AI responses."""
        responses = {
            "analyst": {"verdict": "INVEST", "signal_score": 3, "confidence": 0.85,
                        "reasoning": "Strong signal.", "tickers": ["AAPL"],
                        "risk_factors": [], "key_insights": ["Revenue growth"]},
            "contrarian": {"verdict": "CAUTIOUS", "signal_score": 0, "confidence": 0.6,
                           "reasoning": "Priced in.", "tickers": ["AAPL"],
                           "risk_factors": ["Overreaction"], "key_insights": []},
            "risk": {"verdict": "OBSERVE", "signal_score": 1, "confidence": 0.7,
                     "reasoning": "Manageable risk.", "tickers": ["AAPL"],
                     "risk_factors": ["Supply chain"], "key_insights": []},
            "momentum": {"verdict": "INVEST", "signal_score": 4, "confidence": 0.8,
                         "reasoning": "Strong catalyst.", "tickers": ["AAPL"],
                         "risk_factors": [], "key_insights": ["Momentum building"]},
            "fundamentals": {"verdict": "INVEST", "signal_score": 3, "confidence": 0.75,
                             "reasoning": "Improving margins.", "tickers": ["AAPL"],
                             "risk_factors": [], "key_insights": ["Margin expansion"]},
            "scout": {"verdict": "OBSERVE", "signal_score": 2, "confidence": 0.7,
                      "reasoning": "Credible source, novel info.", "tickers": ["AAPL"],
                      "risk_factors": [], "key_insights": ["Primary source"]},
            "reviewer": {"verdict": "INVEST", "signal_score": 3, "confidence": 0.8,
                         "reasoning": "Claims verified, not yet priced in.", "tickers": ["AAPL"],
                         "risk_factors": [], "key_insights": ["Verifiable data"]},
        }

        prompt_markers = [
            ("contrarian financial analyst", "contrarian"),
            ("risk-focused financial analyst", "risk"),
            ("momentum-focused financial analyst", "momentum"),
            ("fundamentals-focused financial analyst", "fundamentals"),
            ("scout analyst", "scout"),
            ("reviewer analyst", "reviewer"),
            ("senior financial analyst specializing", "analyst"),
        ]

        def mock_call_ai(prompt, system_prompt, model=None):
            lower = system_prompt.lower()
            for marker, key in prompt_markers:
                if marker in lower:
                    return responses[key]
            return responses["analyst"]

        with patch("finscrape.agents.base.call_ai", side_effect=mock_call_ai):
            council = AgentCouncil(agents=DEFAULT_AGENTS)
            result = council.deliberate(
                "Apple Reports Record Q4 Earnings",
                "Apple Inc reported quarterly revenue of $89.5 billion...",
                metadata={"source": "reuters"},
            )

        assert len(result.individual_verdicts) == 8
        assert -5 <= result.consensus_score <= 5
        assert 0.0 <= result.consensus_confidence <= 1.0
        assert 0.0 <= result.agreement_level <= 1.0
        assert result.consensus_verdict in ("INVEST", "OBSERVE", "CAUTIOUS", "PULL_OUT")
        assert isinstance(result.dissenting_agents, list)
        # Verify both new agents produced verdicts
        verdict_names = [v.agent_name for v in result.individual_verdicts]
        assert "scout" in verdict_names
        assert "reviewer" in verdict_names
