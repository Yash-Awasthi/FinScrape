"""
Tests for the debate judge — reads the whole transcript plus the arithmetic
consensus and can override it. All tests use mocked AI responses — no
actual API calls are made.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out finscrape.analysis.ai_client so we never import requests/dotenv
# at module level. Mirrors tests/test_agents.py.
# ---------------------------------------------------------------------------
_ai_client_mod = types.ModuleType("finscrape.analysis.ai_client")
_ai_client_mod.call_ai = MagicMock(return_value=None)
sys.modules["finscrape.analysis.ai_client"] = _ai_client_mod

from finscrape.agents.base import AgentVerdict, BaseAgent
from finscrape.agents.council import AgentCouncil
from finscrape.agents.judge import JudgeVerdict, judge_debate

del sys.modules["finscrape.analysis.ai_client"]


def _make_verdict(agent_name: str, score: int, confidence: float = 0.8) -> AgentVerdict:
    return AgentVerdict(
        agent_name=agent_name,
        verdict=AgentVerdict._verdict_from_score(score),
        signal_score=score,
        confidence=confidence,
        reasoning=f"{agent_name} reasoning for score {score}.",
    )


class DummyAgent(BaseAgent):
    """Concrete agent that returns a fixed response, bypassing the AI call."""

    def __init__(self, fixed_response: dict, agent_name: str, weight: float = 1.0):
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
        return self._parse_response(self._fixed_response)


def _build_agents() -> list[DummyAgent]:
    """Three agents whose weighted mean is exactly +3, with one dissenter."""
    scores = {"agent_0": 5, "agent_1": 5, "agent_2": -1}
    return [
        DummyAgent(
            fixed_response={
                "verdict": AgentVerdict._verdict_from_score(score),
                "signal_score": score,
                "confidence": 0.8,
                "reasoning": f"{name} reasoning for score {score}.",
                "tickers": ["AAPL"],
                "risk_factors": [],
                "key_insights": [],
            },
            agent_name=name,
        )
        for name, score in scores.items()
    ]


# ===================================================================
# judge_debate() unit tests
# ===================================================================

class TestJudgeDebate:

    def test_returns_none_when_ai_dead(self):
        with patch("finscrape.agents.judge.call_ai", return_value=None):
            result = judge_debate(
                [_make_verdict("agent_0", 3)],
                {"consensus_score_raw": 3.0, "agreement_level": 1.0, "dissenting_agents": []},
            )
        assert result is None

    def test_parses_valid_response(self):
        mock_response = {
            "verdict": "PULL_OUT",
            "signal_score": -1,
            "confidence": 0.9,
            "rationale": "The dissenting agent raised a risk the majority underweighted.",
        }
        with patch("finscrape.agents.judge.call_ai", return_value=mock_response):
            result = judge_debate(
                [_make_verdict("agent_0", 5), _make_verdict("agent_2", -1)],
                {"consensus_score_raw": 2.0, "agreement_level": 0.5, "dissenting_agents": ["agent_2"]},
            )
        assert isinstance(result, JudgeVerdict)
        assert result.signal_score == -1
        assert result.verdict == "PULL_OUT"
        assert result.confidence == 0.9
        assert "dissenting agent" in result.rationale

    def test_prompt_contains_agent_names_and_dissenters(self):
        mock_call = MagicMock(return_value={
            "verdict": "CAUTIOUS", "signal_score": 0, "confidence": 0.5, "rationale": "r",
        })
        with patch("finscrape.agents.judge.call_ai", mock_call):
            judge_debate(
                [_make_verdict("agent_0", 5), _make_verdict("agent_1", 5), _make_verdict("agent_2", -1)],
                {"consensus_score_raw": 3.0, "agreement_level": 0.6, "dissenting_agents": ["agent_2"]},
            )
        prompt = mock_call.call_args[0][0]
        assert "agent_0" in prompt
        assert "agent_1" in prompt
        assert "agent_2" in prompt
        assert "['agent_2']" in prompt

    def test_reads_judge_model_env(self, monkeypatch):
        monkeypatch.setenv("FINSCRAPE_JUDGE_MODEL", "expensive/model")
        mock_call = MagicMock(return_value={
            "verdict": "CAUTIOUS", "signal_score": 0, "confidence": 0.5, "rationale": "r",
        })
        with patch("finscrape.agents.judge.call_ai", mock_call):
            judge_debate([_make_verdict("agent_0", 0)],
                          {"consensus_score_raw": 0.0, "agreement_level": 1.0, "dissenting_agents": []})
        assert mock_call.call_args.kwargs["model"] == "expensive/model"

    def test_score_and_confidence_clamped(self):
        mock_response = {"verdict": "INVEST", "signal_score": 99, "confidence": 5.0, "rationale": "r"}
        with patch("finscrape.agents.judge.call_ai", return_value=mock_response):
            result = judge_debate([_make_verdict("agent_0", 5)],
                                   {"consensus_score_raw": 5.0, "agreement_level": 1.0, "dissenting_agents": []})
        assert result.signal_score == 5
        assert result.confidence == 1.0


# ===================================================================
# AgentCouncil(judge=True) integration — judge overrides the arithmetic
# ===================================================================

class TestCouncilJudgeOverride:

    def test_judge_overrides_arithmetic_mean(self):
        """Agents average +3; the judge contradicts them with -1."""
        judge_response = {
            "verdict": "PULL_OUT",
            "signal_score": -1,
            "confidence": 0.9,
            "rationale": "agent_2's risk case outweighs the two bulls.",
        }
        mock_call = MagicMock(return_value=judge_response)
        with patch("finscrape.agents.judge.call_ai", mock_call):
            council = AgentCouncil(agents=_build_agents(), judge=True)
            result = council.deliberate("Test Headline", "Test article body.")

        # (1) judge verdict overrides the arithmetic
        assert result.consensus_score == -1
        assert result.consensus_verdict == "PULL_OUT"
        assert result.judged is True
        assert result.judge_rationale == judge_response["rationale"]

        # (2) raw arithmetic mean survives untouched
        assert result.consensus_score_raw == 3.0

        # (3) judge prompt carried every agent name + the dissenting list
        prompt = mock_call.call_args[0][0]
        assert "agent_0" in prompt
        assert "agent_1" in prompt
        assert "agent_2" in prompt
        assert "agent_2" in result.dissenting_agents
        assert str(result.dissenting_agents) in prompt

    def test_judge_none_is_byte_identical_to_judge_false(self):
        """(4) Judge LLM dead -> falls straight back to today's math, zero regression."""
        with patch("finscrape.agents.judge.call_ai", return_value=None):
            judged_council = AgentCouncil(agents=_build_agents(), judge=True)
            judged_result = judged_council.deliberate("Test Headline", "Test article body.")

        plain_council = AgentCouncil(agents=_build_agents(), judge=False)
        plain_result = plain_council.deliberate("Test Headline", "Test article body.")

        # ThreadPoolExecutor completion order is nondeterministic; sort by
        # agent_name so the comparison isn't sensitive to scheduling.
        def _normalized(d: dict) -> dict:
            d = dict(d)
            d["individual_verdicts"] = sorted(d["individual_verdicts"], key=lambda v: v["agent_name"])
            return d

        assert _normalized(judged_result.to_dict()) == _normalized(plain_result.to_dict())
        assert judged_result.judged is False
        assert judged_result.consensus_score == judged_result.consensus_score_raw == 3.0
