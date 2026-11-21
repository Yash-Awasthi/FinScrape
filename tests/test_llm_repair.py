"""The LLM boundary: schema validation and the one repair attempt (plan m1.3.1).

No network: `ai_client._dispatch` is replaced with a fake model, so these tests pin the
contract call_ai now has — a reply either satisfies the schema, is repaired once, or is
refused and logged. It is never silently patched up into a heuristic-shaped answer.
"""

from __future__ import annotations

import json
import logging

import pytest

from finscrape.analysis import ai_client
from finscrape.analysis.reply_schema import redacted_sample, repair_prompt, reply_errors

GOOD = {
    "relevant": True,
    "event_type": "earnings",
    "impact_direction": "positive",
    "signal_score": 3,
    "confidence": 0.72,
    "subject": "Acme beats estimates",
    "reasoning": "Q3 revenue above guidance.",
    "tickers": ["ACME"],
}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """No fallback chain and no cached replies leaking between tests."""
    monkeypatch.setenv("FINSCRAPE_MODEL_FALLBACK", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    ai_client.clear_cache()
    ai_client._last_reply.text = ""
    yield
    ai_client.clear_cache()


def _reply(text: str) -> dict | None:
    """What a backend does: remember the raw text, then parse it exactly like production."""
    return ai_client._extract_json_from_text(text)


def test_a_usable_reply_is_stamped_as_model(monkeypatch):
    monkeypatch.setattr(ai_client, "_dispatch", lambda *a: _reply(json.dumps(GOOD)))

    result = ai_client.call_ai("prompt: usable reply", "system")

    assert result is not None
    assert result["analysis_source"] == "model"
    assert result["model_name"]
    assert result["signal_score"] == 3


def test_unparseable_reply_is_repaired_once(monkeypatch):
    prompts: list[str] = []

    def fake_dispatch(prompt, system_prompt, model):
        prompts.append(prompt)
        if len(prompts) == 1:
            return _reply("Sure! Here is the analysis: it looks positive.")
        return _reply(json.dumps(GOOD))

    monkeypatch.setattr(ai_client, "_dispatch", fake_dispatch)

    result = ai_client.call_ai("prompt: prose reply", "system")

    assert len(prompts) == 2, "exactly one repair attempt"
    assert "Sure! Here is the analysis" in prompts[1], "the repair prompt quotes the model"
    assert result["analysis_source"] == "model_repaired"
    assert result["signal_score"] == 3


def test_schema_violation_is_repaired_once(monkeypatch):
    prompts: list[str] = []

    def fake_dispatch(prompt, system_prompt, model):
        prompts.append(prompt)
        if len(prompts) == 1:
            return _reply(json.dumps({"relevant": True, "signal_score": 42}))
        return _reply(json.dumps(GOOD))

    monkeypatch.setattr(ai_client, "_dispatch", fake_dispatch)

    result = ai_client.call_ai("prompt: out of range", "system")

    assert len(prompts) == 2
    assert "signal_score" in prompts[1], "the schema error is quoted back"
    assert result["analysis_source"] == "model_repaired"


def test_two_bad_replies_are_refused_not_patched(monkeypatch, caplog):
    monkeypatch.setattr(ai_client, "_dispatch", lambda *a: _reply("still not json"))

    with caplog.at_level(logging.WARNING):
        result = ai_client.call_ai("prompt: unrecoverable", "system")

    assert result is None, "a downgraded event must be explicit, never a patched reply"
    assert "json_invalid" in caplog.text
    assert "repair_failed" in caplog.text


def test_schema_invalid_names_the_model_and_the_problem(monkeypatch, caplog):
    monkeypatch.setattr(ai_client, "_dispatch", lambda *a: _reply(json.dumps({"signal_score": 1})))

    with caplog.at_level(logging.WARNING):
        result = ai_client.call_ai("prompt: missing relevant", "system")

    assert result is None
    assert "schema_invalid" in caplog.text
    assert "relevant: Field required" in caplog.text


def test_a_model_that_never_answers_is_not_repaired(monkeypatch):
    prompts: list[str] = []

    def fake_dispatch(prompt, system_prompt, model):
        prompts.append(prompt)
        ai_client._last_reply.text = ""  # the backend failed before any text arrived
        return _reply(None)

    monkeypatch.setattr(ai_client, "_dispatch", fake_dispatch)

    assert ai_client.call_ai("prompt: no answer", "system") is None
    assert len(prompts) == 1, "a transport failure has nothing to repair"


def test_schema_flags_shape_not_spelling():
    # Nulls and numeric strings are model quirks the client already coerces, so they must not
    # cost an extra API call; a missing required field or an out-of-range score must.
    assert reply_errors({"relevant": True, "signal_score": None, "confidence": "0.4"}) == []
    assert reply_errors({"relevant": True, "tickers": None}) == []
    assert reply_errors({"signal_score": 1}) == ["relevant: Field required"]
    assert reply_errors({"relevant": True, "signal_score": 9})
    assert reply_errors(["not", "an", "object"])


def test_redaction_bounds_what_is_logged():
    sample = redacted_sample("x" * 5000)

    assert len(sample) <= 401
    assert sample.endswith("…")


def test_repair_prompt_carries_the_problems_and_forbids_prose():
    prompt = repair_prompt("ORIGINAL", "previous text", ["signal_score: too big"])

    assert prompt.startswith("ORIGINAL")
    assert "- signal_score: too big" in prompt
    assert "Previous reply:\nprevious text" in prompt
    assert "no code fence" in prompt


def test_the_event_row_carries_the_source_and_model():
    from finscrape.models import FinEvent

    event = FinEvent.from_dict(
        {
            "subject": "Acme beats estimates",
            "event_type": "earnings",
            "tickers": ["ACME"],
            "impact_direction": "positive",
            "signal_score": 3,
            "confidence": 0.7,
            "verdict": "INVEST",
            "analysis_source": "model_repaired",
            "model_name": "deepseek-v4.1-flash:free",
        }
    )

    assert event.analysis_source == "model_repaired"
    assert event.model_name == "deepseek-v4.1-flash:free"


def test_the_ingest_statement_writes_both_columns_in_order():
    from server.ingest import _INSERT_COLS, _row_values

    assert _INSERT_COLS.index("analysis_source") == _INSERT_COLS.index("key_metrics") + 1
    assert _INSERT_COLS.index("model_name") == _INSERT_COLS.index("analysis_source") + 1

    values = _row_values(
        {
            "subject": "Acme beats estimates",
            "event_type": "earnings",
            "verdict": "INVEST",
            "timestamp": "2026-11-24T12:00:00Z",
            "analysis_source": "heuristic",
        }
    )

    assert values[_INSERT_COLS.index("analysis_source")] == "heuristic"
    assert values[_INSERT_COLS.index("model_name")] == "", "no model wrote a heuristic row"


def test_the_migration_labels_old_rows_unknown_rather_than_guessing():
    from pathlib import Path

    sql = Path("server/migrations/0014_event_analysis_source.sql").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS analysis_source TEXT NOT NULL DEFAULT 'unknown'" in sql
    assert "ADD COLUMN IF NOT EXISTS model_name" in sql
    assert "idx_events_analysis_source" in sql
