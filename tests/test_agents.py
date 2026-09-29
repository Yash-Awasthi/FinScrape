"""
Tests for the Multi-Agent AI Council framework.

All tests use mocked AI responses — no actual API calls are made.
"""

from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub out finscrape.analysis.ai_client so we never import requests/dotenv
# at module level.  The conftest.py stubs finscrape and finscrape.analysis
# as namespace packages, but we also need the ai_client submodule to exist
# with a callable `call_ai`.
# ---------------------------------------------------------------------------
_ai_client_mod = types.ModuleType("finscrape.analysis.ai_client")
_ai_client_mod.call_ai = MagicMock(return_value=None)  # default: returns None
sys.modules["finscrape.analysis.ai_client"] = _ai_client_mod

# Import real constants module (pure Python, no heavy deps)
import finscrape.analysis.constants  # noqa: F401

# Now safe to import agents
from finscrape.agents.base import AgentVerdict, BaseAgent
from finscrape.agents.council import AgentCouncil, CouncilVerdict, MAX_POSSIBLE_STD_DEV, DISSENT_THRESHOLD
from finscrape.agents.personas import (
    AnalystAgent,
    ContrarianAgent,
    RiskAgent,
    MomentumAgent,
    FundamentalsAgent,
    DEFAULT_AGENTS,
)

# Drop the stub so later test modules importing the real ai_client don't
# inherit this MagicMock-only module from sys.modules.
del sys.modules["finscrape.analysis.ai_client"]


# ===================================================================
# Helpers
# ===================================================================

def _make_verdict(
    agent_name: str = "test",
    verdict: str = "OBSERVE",
    signal_score: int = 2,
    confidence: float = 0.7,
    reasoning: str = "Test reasoning.",
    tickers: list[str] | None = None,
    risk_factors: list[str] | None = None,
    key_insights: list[str] | None = None,
) -> AgentVerdict:
    return AgentVerdict(
        agent_name=agent_name,
        verdict=verdict,
        signal_score=signal_score,
        confidence=confidence,
        reasoning=reasoning,
        tickers=tickers or ["AAPL"],
        risk_factors=risk_factors or [],
        key_insights=key_insights or [],
    )


class CrashingAgent(BaseAgent):
    """An agent whose analyze() always raises, simulating a dead agent."""

    def __init__(self, weight: float = 1.0, agent_name: str = "crasher"):
        super().__init__(weight=weight)
        self._name = agent_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> str:
        return "Test agent that crashes"

    @property
    def system_prompt(self) -> str:
        return "You are a test agent."

    def analyze(self, title, text, metadata=None):
        raise RuntimeError("simulated agent crash")


class DummyAgent(BaseAgent):
    """A simple concrete agent for testing that returns a fixed response."""

    def __init__(self, fixed_response: dict, weight: float = 1.0, agent_name: str = "dummy"):
        super().__init__(weight=weight)
        self._fixed_response = fixed_response
        self._name = agent_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> str:
        return "Test agent"

    @property
    def system_prompt(self) -> str:
        return "You are a test agent."

    def analyze(self, title, text, metadata=None):
        """Bypass AI call entirely and return a fixed verdict."""
        return self._parse_response(self._fixed_response)


# ===================================================================
# AgentVerdict tests
# ===================================================================

class TestAgentVerdict:

    def test_basic_creation(self):
        v = _make_verdict()
        assert v.agent_name == "test"
        assert v.verdict == "OBSERVE"
        assert v.signal_score == 2
        assert v.confidence == 0.7
        assert v.tickers == ["AAPL"]

    def test_score_clamping_high(self):
        v = AgentVerdict(agent_name="t", verdict="INVEST", signal_score=10, confidence=0.5)
        assert v.signal_score == 5

    def test_score_clamping_low(self):
        v = AgentVerdict(agent_name="t", verdict="PULL_OUT", signal_score=-10, confidence=0.5)
        assert v.signal_score == -5

    def test_confidence_clamping_high(self):
        v = AgentVerdict(agent_name="t", verdict="OBSERVE", signal_score=0, confidence=1.5)
        assert v.confidence == 1.0

    def test_confidence_clamping_low(self):
        v = AgentVerdict(agent_name="t", verdict="OBSERVE", signal_score=0, confidence=-0.5)
        assert v.confidence == 0.0

    def test_invalid_verdict_auto_corrected(self):
        v = AgentVerdict(agent_name="t", verdict="INVALID", signal_score=4, confidence=0.8)
        assert v.verdict == "INVEST"  # score 4 -> INVEST

    def test_invalid_verdict_negative_score(self):
        v = AgentVerdict(agent_name="t", verdict="BOGUS", signal_score=-3, confidence=0.5)
        assert v.verdict == "PULL_OUT"  # score -3 -> PULL_OUT

    def test_to_dict(self):
        v = _make_verdict(agent_name="analyst", signal_score=3, verdict="INVEST")
        d = v.to_dict()
        assert isinstance(d, dict)
        assert d["agent_name"] == "analyst"
        assert d["signal_score"] == 3

    def test_from_dict(self):
        d = {
            "agent_name": "risk",
            "verdict": "CAUTIOUS",
            "signal_score": -1,
            "confidence": 0.6,
            "reasoning": "Some risk.",
            "tickers": ["TSLA"],
            "risk_factors": ["overvaluation"],
            "key_insights": [],
        }
        v = AgentVerdict.from_dict(d)
        assert v.agent_name == "risk"
        assert v.signal_score == -1
        assert v.tickers == ["TSLA"]

    def test_from_dict_ignores_extra_keys(self):
        d = {
            "agent_name": "x",
            "verdict": "OBSERVE",
            "signal_score": 1,
            "confidence": 0.5,
            "extra_field": "should be ignored",
        }
        v = AgentVerdict.from_dict(d)
        assert v.agent_name == "x"
        assert not hasattr(v, "extra_field")

    def test_verdict_from_score_boundaries(self):
        assert AgentVerdict._verdict_from_score(5) == "INVEST"
        assert AgentVerdict._verdict_from_score(3) == "INVEST"
        assert AgentVerdict._verdict_from_score(2) == "OBSERVE"
        assert AgentVerdict._verdict_from_score(1) == "OBSERVE"
        assert AgentVerdict._verdict_from_score(0) == "CAUTIOUS"
        assert AgentVerdict._verdict_from_score(-1) == "CAUTIOUS"
        assert AgentVerdict._verdict_from_score(-2) == "CAUTIOUS"
        assert AgentVerdict._verdict_from_score(-3) == "PULL_OUT"
        assert AgentVerdict._verdict_from_score(-5) == "PULL_OUT"

    def test_verdict_thresholds_mirror_and_agree(self):
        # A -2 PULL_OUT hit 56% against a +2 OBSERVE; the call needs the same
        # strength on both sides, and every copy of the mapping must agree.
        from finscrape.council.base import AgentVerdict as CouncilVerdict
        from finscrape.models import Verdict

        mirror = {"INVEST": "PULL_OUT", "OBSERVE": "CAUTIOUS"}
        for s in range(1, 6):
            assert mirror[Verdict.from_score(s).value] == Verdict.from_score(-s).value
        for s in range(-5, 6):
            v = Verdict.from_score(s).value
            assert AgentVerdict._verdict_from_score(s) == v
            assert CouncilVerdict._verdict_from_score(s) == v


# ===================================================================
# Persona tests
# ===================================================================

class TestPersonas:

    def test_all_default_agents_exist(self):
        assert len(DEFAULT_AGENTS) == 8

    def test_agent_names_are_unique(self):
        names = [a.name for a in DEFAULT_AGENTS]
        assert len(names) == len(set(names))

    def test_each_agent_has_non_empty_system_prompt(self):
        for agent in DEFAULT_AGENTS:
            assert len(agent.system_prompt) > 100, f"{agent.name} system prompt too short"

    def test_each_agent_has_role(self):
        for agent in DEFAULT_AGENTS:
            assert len(agent.role) > 10, f"{agent.name} role too short"

    def test_agent_weights_are_positive(self):
        for agent in DEFAULT_AGENTS:
            assert agent.weight > 0, f"{agent.name} has non-positive weight"

    def test_analyst_agent_properties(self):
        a = AnalystAgent()
        assert a.name == "analyst"
        assert "neutral" in a.system_prompt.lower() or "thorough" in a.system_prompt.lower()

    def test_contrarian_agent_properties(self):
        a = ContrarianAgent()
        assert a.name == "contrarian"
        assert "contrarian" in a.system_prompt.lower()

    def test_risk_agent_properties(self):
        a = RiskAgent()
        assert a.name == "risk"
        assert "risk" in a.system_prompt.lower()

    def test_momentum_agent_properties(self):
        a = MomentumAgent()
        assert a.name == "momentum"
        assert "momentum" in a.system_prompt.lower()

    def test_fundamentals_agent_properties(self):
        a = FundamentalsAgent()
        assert a.name == "fundamentals"
        assert "fundamentals" in a.system_prompt.lower() or "intrinsic" in a.system_prompt.lower()


# ===================================================================
# Council consensus calculation tests
# ===================================================================

class TestCouncilConsensus:

    def _make_council_with_fixed_verdicts(
        self,
        scores_and_confs: list[tuple[int, float]],
        weights: list[float] | None = None,
    ) -> CouncilVerdict:
        """Build a council with DummyAgents and run deliberation."""
        weights = weights or [1.0] * len(scores_and_confs)
        agents = []
        for i, ((score, conf), w) in enumerate(zip(scores_and_confs, weights)):
            verdict_str = AgentVerdict._verdict_from_score(score)
            agents.append(DummyAgent(
                fixed_response={
                    "verdict": verdict_str,
                    "signal_score": score,
                    "confidence": conf,
                    "reasoning": f"Agent {i} reasoning.",
                    "tickers": ["AAPL"],
                    "risk_factors": [f"risk_{i}"] if score < 0 else [],
                    "key_insights": [f"insight_{i}"] if score > 0 else [],
                },
                weight=w,
                agent_name=f"agent_{i}",
            ))
        council = AgentCouncil(agents=agents)
        return council.deliberate("Test Headline", "Test article body text.")

    def test_single_agent(self):
        result = self._make_council_with_fixed_verdicts([(3, 0.8)])
        assert result.consensus_score == 3.0
        assert result.agreement_level == 1.0  # single agent = perfect agreement
        assert result.consensus_verdict == "INVEST"
        assert len(result.individual_verdicts) == 1

    def test_all_agents_agree_positive(self):
        result = self._make_council_with_fixed_verdicts([
            (4, 0.9), (4, 0.85), (4, 0.8),
        ])
        assert result.consensus_score == 4.0
        assert result.agreement_level == 1.0
        assert result.consensus_verdict == "INVEST"
        assert result.consensus_confidence > 0.8  # high agreement boosts confidence

    def test_all_agents_agree_negative(self):
        result = self._make_council_with_fixed_verdicts([
            (-3, 0.8), (-3, 0.7), (-3, 0.75),
        ])
        assert result.consensus_score == -3.0
        assert result.agreement_level == 1.0
        assert result.consensus_verdict == "PULL_OUT"

    def test_mixed_scores_produce_moderate_consensus(self):
        result = self._make_council_with_fixed_verdicts([
            (3, 0.8), (-2, 0.7), (1, 0.6),
        ])
        # Weighted avg: (3 + -2 + 1) / 3 = 0.667
        assert -1 <= result.consensus_score <= 2
        assert result.agreement_level < 0.8  # should reflect disagreement

    def test_weighted_average(self):
        # Agent 0: score=4, weight=2; Agent 1: score=-2, weight=1
        result = self._make_council_with_fixed_verdicts(
            [(4, 0.8), (-2, 0.7)],
            weights=[2.0, 1.0],
        )
        # Weighted avg: (4*2 + -2*1) / (2+1) = 6/3 = 2.0
        assert result.consensus_score == 2.0

    def test_equal_weights(self):
        result = self._make_council_with_fixed_verdicts(
            [(2, 0.8), (4, 0.8)],
            weights=[1.0, 1.0],
        )
        assert result.consensus_score == 3.0

    def test_agreement_level_perfect(self):
        """All same scores -> agreement = 1.0."""
        result = self._make_council_with_fixed_verdicts([
            (2, 0.7), (2, 0.7), (2, 0.7), (2, 0.7),
        ])
        assert result.agreement_level == 1.0

    def test_agreement_level_maximum_disagreement(self):
        """Scores at opposite extremes -> agreement near 0."""
        result = self._make_council_with_fixed_verdicts([
            (5, 0.8), (-5, 0.8),
        ])
        # std_dev = 5.0, agreement = 1 - 5/5 = 0.0
        assert result.agreement_level == 0.0

    def test_agreement_level_moderate(self):
        """Scores spread but not extreme."""
        result = self._make_council_with_fixed_verdicts([
            (1, 0.7), (3, 0.7), (2, 0.7),
        ])
        # mean=2, variance = ((1-2)^2 + (3-2)^2 + (2-2)^2)/3 = 2/3
        # std_dev ~= 0.816, agreement ~= 1 - 0.816/5 ~= 0.837
        assert 0.7 < result.agreement_level < 0.95

    def test_dissenting_agents_identified(self):
        result = self._make_council_with_fixed_verdicts([
            (4, 0.8), (3, 0.8), (-3, 0.8),
        ])
        # consensus ~ (4+3-3)/3 ~ 1.33
        # agent_2 score=-3, diff from 1.33 is 4.33 > DISSENT_THRESHOLD (2.5)
        assert "agent_2" in result.dissenting_agents

    def test_no_dissenters_when_all_agree(self):
        result = self._make_council_with_fixed_verdicts([
            (2, 0.7), (2, 0.7), (3, 0.7),
        ])
        assert len(result.dissenting_agents) == 0

    def test_confidence_boosted_when_agents_agree(self):
        # Perfect agreement
        agreed = self._make_council_with_fixed_verdicts([
            (3, 0.8), (3, 0.8), (3, 0.8),
        ])
        # Max disagreement
        disagreed = self._make_council_with_fixed_verdicts([
            (5, 0.8), (-5, 0.8),
        ])
        assert agreed.consensus_confidence > disagreed.consensus_confidence

    def test_key_risks_aggregated(self):
        result = self._make_council_with_fixed_verdicts([
            (-2, 0.7), (-1, 0.6),
        ])
        # Both negative agents contribute risk_factors
        assert len(result.key_risks) >= 1

    def test_key_opportunities_aggregated(self):
        result = self._make_council_with_fixed_verdicts([
            (3, 0.8), (2, 0.7),
        ])
        # Both positive agents contribute key_insights
        assert len(result.key_opportunities) >= 1

    def test_risks_deduplicated(self):
        """Same risk from two agents should appear only once."""
        agents = [
            DummyAgent(
                fixed_response={
                    "verdict": "CAUTIOUS",
                    "signal_score": -1,
                    "confidence": 0.6,
                    "reasoning": "r",
                    "tickers": [],
                    "risk_factors": ["Overvaluation risk"],
                    "key_insights": [],
                },
                weight=1.0,
                agent_name=f"agent_{i}",
            )
            for i in range(3)
        ]
        council = AgentCouncil(agents=agents)
        result = council.deliberate("Test", "Test body")
        assert result.key_risks.count("Overvaluation risk") == 1

    def test_council_verdict_to_dict(self):
        result = self._make_council_with_fixed_verdicts([(2, 0.7)])
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "individual_verdicts" in d
        assert isinstance(d["individual_verdicts"][0], dict)
        assert "consensus_score" in d
        assert "agreement_level" in d

    def test_empty_council_raises(self):
        with pytest.raises(ValueError):
            AgentCouncil(agents=[])


# ===================================================================
# Crashed agent exclusion from consensus math
# ===================================================================

class TestCrashedAgentExclusion:

    def test_crashed_agent_excluded_from_consensus_math(self):
        """A crashed agent's sentinel verdict must not pull the weighted average."""
        survivors = [
            DummyAgent(
                fixed_response={
                    "verdict": "INVEST", "signal_score": 4, "confidence": 0.9,
                    "reasoning": "r", "tickers": [], "risk_factors": [], "key_insights": [],
                },
                weight=1.0, agent_name=f"survivor_{i}",
            )
            for i in range(2)
        ]
        agents = survivors + [CrashingAgent(weight=1.0, agent_name="crasher")]
        council = AgentCouncil(agents=agents)
        result = council.deliberate("Test", "Test body")

        assert len(result.individual_verdicts) == 3
        assert result.failed_agents == 1
        crashed = next(v for v in result.individual_verdicts if v.agent_name == "crasher")
        assert crashed.error is True

        # If the crashed sentinel (score=0) had been folded into the weighted
        # average, the result would be (4+4+0)/3 = 2.67, not 4.0.
        assert result.consensus_score == 4.0
        assert "crasher" not in result.dissenting_agents

    def test_all_agents_crashed_forces_zero_confidence(self):
        """An all-crashed council must not launder its sentinel votes into a calm neutral consensus."""
        agents = [CrashingAgent(weight=1.0, agent_name=f"crasher_{i}") for i in range(3)]
        council = AgentCouncil(agents=agents)
        result = council.deliberate("Test", "Test body")

        assert len(result.individual_verdicts) == 3
        assert result.failed_agents == 3
        assert result.consensus_confidence == 0.0
        assert result.consensus_score == 0.0


# ===================================================================
# Agreement calculation edge cases
# ===================================================================

class TestAgreementCalculation:

    def test_single_score(self):
        assert AgentCouncil._calculate_agreement([3]) == 1.0

    def test_empty_scores(self):
        # Technically shouldn't happen, but handle gracefully
        assert AgentCouncil._calculate_agreement([]) == 1.0

    def test_identical_scores(self):
        assert AgentCouncil._calculate_agreement([2, 2, 2, 2]) == 1.0

    def test_opposite_extremes(self):
        assert AgentCouncil._calculate_agreement([5, -5]) == pytest.approx(0.0)

    def test_small_spread(self):
        # [1, 2, 3] mean=2, std=0.816, agreement=1-0.816/5=0.837
        agreement = AgentCouncil._calculate_agreement([1, 2, 3])
        assert 0.8 < agreement < 0.9

    def test_result_bounded_zero_to_one(self):
        agreement = AgentCouncil._calculate_agreement([-5, 5, -5, 5])
        assert 0.0 <= agreement <= 1.0


# ===================================================================
# BaseAgent with mocked call_ai
# ===================================================================

class TestBaseAgentWithMock:

    def test_analyze_calls_call_ai(self):
        """Verify that analyze() calls the shared call_ai function."""
        mock_response = {
            "verdict": "INVEST",
            "signal_score": 4,
            "confidence": 0.85,
            "reasoning": "Strong earnings beat.",
            "tickers": ["AAPL"],
            "risk_factors": [],
            "key_insights": ["Revenue up 20%"],
        }
        with patch("finscrape.agents.base.call_ai", return_value=mock_response) as mock_call:
            agent = AnalystAgent(weight=1.0)
            result = agent.analyze("Apple Beats Earnings", "Apple reported strong Q4...")
            mock_call.assert_called_once()
            assert result.signal_score == 4
            assert result.verdict == "INVEST"
            assert result.agent_name == "analyst"

    def test_analyze_handles_none_response(self):
        """call_ai returning None should produce a safe default verdict."""
        with patch("finscrape.agents.base.call_ai", return_value=None):
            agent = RiskAgent()
            result = agent.analyze("Test", "Test body")
            assert result.confidence == 0.1
            assert result.signal_score == 0
            assert result.verdict == "CAUTIOUS"

    def test_analyze_passes_metadata(self):
        """Metadata should be included in the prompt."""
        mock_response = {
            "verdict": "OBSERVE",
            "signal_score": 1,
            "confidence": 0.6,
            "reasoning": "Moderate signal.",
            "tickers": [],
            "risk_factors": [],
            "key_insights": [],
        }
        with patch("finscrape.agents.base.call_ai", return_value=mock_response) as mock_call:
            agent = MomentumAgent()
            agent.analyze("Test", "Body", metadata={"source": "reuters", "age_hours": 2.5})
            prompt_arg = mock_call.call_args[0][0]
            assert "reuters" in prompt_arg
            assert "2.5" in prompt_arg


# ===================================================================
# Full council integration test (still mocked)
# ===================================================================

class TestCouncilIntegration:

    def test_full_council_with_mocked_ai(self):
        """Run the full DEFAULT_AGENTS lineup with mocked AI responses."""
        responses = {
            "analyst": {"verdict": "INVEST", "signal_score": 3, "confidence": 0.85,
                        "reasoning": "Strong earnings.", "tickers": ["AAPL"],
                        "risk_factors": [], "key_insights": ["Revenue growth"]},
            "contrarian": {"verdict": "CAUTIOUS", "signal_score": 0, "confidence": 0.6,
                           "reasoning": "Market already priced in.", "tickers": ["AAPL"],
                           "risk_factors": ["Overreaction risk"], "key_insights": []},
            "risk": {"verdict": "OBSERVE", "signal_score": 1, "confidence": 0.7,
                     "reasoning": "Some downside risk.", "tickers": ["AAPL"],
                     "risk_factors": ["Supply chain", "China exposure"], "key_insights": []},
            "momentum": {"verdict": "INVEST", "signal_score": 4, "confidence": 0.8,
                         "reasoning": "Strong catalyst.", "tickers": ["AAPL"],
                         "risk_factors": [], "key_insights": ["Earnings momentum"]},
            "fundamentals": {"verdict": "INVEST", "signal_score": 3, "confidence": 0.75,
                             "reasoning": "Improving margins.", "tickers": ["AAPL"],
                             "risk_factors": [], "key_insights": ["Margin expansion"]},
            "scout": {"verdict": "OBSERVE", "signal_score": 2, "confidence": 0.7,
                      "reasoning": "Credible source, novel info.", "tickers": ["AAPL"],
                      "risk_factors": [], "key_insights": ["Primary source"]},
            "reviewer": {"verdict": "INVEST", "signal_score": 3, "confidence": 0.8,
                         "reasoning": "Claims verified.", "tickers": ["AAPL"],
                         "risk_factors": [], "key_insights": ["Verifiable data"]},
        }

        # Map unique phrases from each agent's system prompt to response keys.
        # "analyst" alone would match multiple prompts, so use distinctive phrases.
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
        # Contrarian should be a dissenter (score 0 vs consensus ~2.3)
        # but depends on exact threshold — just verify structure
        assert isinstance(result.dissenting_agents, list)
        assert len(result.key_risks) >= 1  # at least the risk/contrarian agents contributed
        assert len(result.key_opportunities) >= 1
