"""The cost page's numbers come from `scripts/cost_model`, not from memory."""

from __future__ import annotations

import pytest

from scripts.cost_model import estimate_tokens, model


def test_the_token_estimate_is_the_documented_chars_over_four():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 9) == 3


def test_the_per_event_cost_is_the_sum_of_both_sides():
    cost = model(input_per_m=1.0, output_per_m=1.0, repair_rate=0.0)
    expected = (cost.input_tokens + cost.output_tokens) / 1_000_000
    assert cost.per_event_usd == pytest.approx(expected, abs=1e-9)


def test_a_repair_rate_multiplies_the_event_cost():
    base = model(input_per_m=1.0, output_per_m=1.0, repair_rate=0.0)
    repaired = model(input_per_m=1.0, output_per_m=1.0, repair_rate=0.10)
    assert repaired.per_event_usd == pytest.approx(base.per_event_usd * 1.10, rel=1e-3)


def test_reads_are_priced_by_bandwidth_not_tokens():
    cost = model(plan_usd=10.0, plan_gb=5.0, read_kb=10.0)
    # 10,000 reads * 10 KB = 0.1 GB; 0.1/5 of a $10 plan is $0.20.
    assert cost.per_10k_reads_usd == pytest.approx(0.20, abs=0.01)


def test_the_default_event_is_a_thousand_tokens_or_more():
    cost = model()
    assert cost.input_tokens > 1_000
    assert cost.output_tokens > 50
