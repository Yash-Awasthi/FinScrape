"""The on-demand summary must be grounded in the stored analysis.

Before this, the prompt sent only the 12-word subject, so a "summary" could only
restate the headline or invent detail. These pin the context that fixes it.
"""

from __future__ import annotations

from server.ai import _prompt

EVENT = {
    "subject": "Iran halts crude exports after Hormuz closure",
    "verdict": "CAUTIOUS",
    "signal_score": -3,
    "tickers": ["XOM", "CVX"],
    "event_type": "supply_shock",
    "impact_direction": "negative",
    "sources": ["world_rss", "reuters_wire"],
    "sector_impact": "energy",
    "magnitude": "high",
    "novelty": "breaking",
    "actionability": "high",
    "reasoning": "Closure blocks crude shipments; refiners face higher feedstock costs.",
    "affected_entities": [
        {"name": "ExxonMobil", "ticker": "XOM", "role": "producer"},
        {"name": "Chevron", "ticker": "CVX", "role": "producer"},
    ],
    "second_order_effects": [
        "Freight and insurance costs rise",
        "Refining margins compress",
    ],
    "key_metrics": {"export_volume": {"value": -40, "raw": "percent"}},
}


def test_prompt_carries_the_reasoning_and_evidence():
    prompt = _prompt(EVENT)
    assert "Closure blocks crude shipments" in prompt
    assert "ExxonMobil (XOM)" in prompt
    assert "Sector: energy" in prompt
    assert "Second-order effects:" in prompt
    assert "export_volume" in prompt
    assert "Chevron" in prompt


def test_prompt_tells_the_model_not_to_invent():
    from server.ai import _SYSTEM

    assert "never invent" in _SYSTEM.lower()
    assert "the only facts you may use" in _prompt(EVENT).lower()


def test_absent_optional_fields_do_not_leave_empty_labels():
    prompt = _prompt(
        {"subject": "x", "verdict": "OBSERVE", "tickers": [], "sources": []}
    )
    assert "Affected entities:" not in prompt
    assert "Second-order effects:" not in prompt
    assert "Key metrics:" not in prompt
    assert "Sources: unknown" in prompt


def test_long_reasoning_is_bounded():
    prompt = _prompt({**EVENT, "reasoning": "word " * 1000})
    reasoning_line = next(
        line for line in prompt.splitlines() if line.startswith("Reasoning:")
    )
    assert len(reasoning_line) <= 920
    assert reasoning_line.endswith("…")
