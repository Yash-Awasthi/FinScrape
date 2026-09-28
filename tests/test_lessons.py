"""
Tests for the judge's LESSONS block. Debators never see lessons — only the judge
prompt does, and only when lessons are supplied.

All AI calls are mocked — no network, no real LLM.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# Same ai_client stubbing trick as tests/test_judge.py and tests/test_agents.py:
# fake out finscrape.analysis.ai_client before importing finscrape.agents.judge
# so the import chain stays offline (no requests/dotenv).
_ai_client_mod = types.ModuleType("finscrape.analysis.ai_client")
_ai_client_mod.call_ai = MagicMock(return_value=None)
sys.modules["finscrape.analysis.ai_client"] = _ai_client_mod

import finscrape.analysis.constants  # noqa: F401
from finscrape.agents.base import AgentVerdict
from finscrape.agents.judge import format_lessons_block, judge_debate

del sys.modules["finscrape.analysis.ai_client"]


LESSONS = {
    "tickers": {"AAPL": {"total": 5, "correct": 1, "hit_rate_pct": 20.0}},
    "sources": {"yahoo": {"total": 5, "correct": 1, "hit_rate_pct": 20.0}},
    "wrong_calls": [
        {
            "ticker": "AAPL",
            "verdict": "INVEST",
            "price_change_pct": -3.5,
            "source": "yahoo",
            "event_type": "earnings",
        }
    ],
}


def _dummy_verdicts() -> list[AgentVerdict]:
    return [
        AgentVerdict(agent_name="analyst", verdict="INVEST", signal_score=3, confidence=0.8,
                     reasoning="Strong quarter."),
        AgentVerdict(agent_name="risk", verdict="CAUTIOUS", signal_score=-1, confidence=0.6,
                     reasoning="Margin pressure."),
    ]


def _dummy_stats() -> dict:
    return {"consensus_score_raw": 1.0, "agreement_level": 0.5, "dissenting_agents": []}


# ---------------------------------------------------------------------------
# LESSONS block in the judge prompt only
# ---------------------------------------------------------------------------

class TestJudgeLessonsBlock:
    def test_lessons_injected_into_judge_prompt(self):
        lessons = LESSONS

        mock_call = MagicMock(return_value={
            "verdict": "CAUTIOUS", "signal_score": 0, "confidence": 0.5, "rationale": "r",
        })
        with patch("finscrape.agents.judge.call_ai", mock_call):
            judge_debate(_dummy_verdicts(), _dummy_stats(), lessons=lessons)

        prompt = mock_call.call_args[0][0]
        assert "LESSONS" in prompt
        assert "AAPL" in prompt
        assert "20" in prompt  # 20.0% hit rate

    def test_empty_lessons_leave_no_block_in_judge_prompt(self):
        """No lessons -> the judge prompt carries no LESSONS block at all."""
        lessons: dict = {}
        assert format_lessons_block(lessons) == ""

        mock_call = MagicMock(return_value={
            "verdict": "CAUTIOUS", "signal_score": 0, "confidence": 0.5, "rationale": "r",
        })
        with patch("finscrape.agents.judge.call_ai", mock_call):
            judge_debate(_dummy_verdicts(), _dummy_stats(), lessons=lessons)

        prompt = mock_call.call_args[0][0]
        assert "LESSONS" not in prompt

    def test_no_lessons_arg_is_byte_identical_to_empty_lessons(self):
        """Old call sites that never pass `lessons` must see the exact same prompt
        as one passed an explicitly empty dict — zero regression for existing callers."""
        mock_call = MagicMock(return_value={
            "verdict": "CAUTIOUS", "signal_score": 0, "confidence": 0.5, "rationale": "r",
        })
        with patch("finscrape.agents.judge.call_ai", mock_call):
            judge_debate(_dummy_verdicts(), _dummy_stats())
            no_lessons_prompt = mock_call.call_args[0][0]

            judge_debate(_dummy_verdicts(), _dummy_stats(), lessons={})
            empty_lessons_prompt = mock_call.call_args[0][0]

        assert no_lessons_prompt == empty_lessons_prompt
