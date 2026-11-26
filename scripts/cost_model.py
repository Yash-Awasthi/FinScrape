"""Measure the token shape of one analysed event and price it.

The repo can measure everything except the provider's invoice: the prompt it sends,
the reply it expects, and the per-read payload. This script turns those into tokens with a
documented chars/4 estimate and multiplies by a price you supply. It is the source of the
numbers in `docs/COST.md`, so the page moves when the prompt or the reply schema moves.

    uv run -p 3.14 --group server --group dev python -m scripts.cost_model
    ... --input-per-m 0.27 --output-per-m 1.10 --read-kb 10

The token estimate is approximate (model tokenizers vary by a few percent); the prices are
arguments, not constants, because a provider invoice is the only authority on them.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass

from finscrape.analysis.prompts import ANALYSIS_PROMPT, SYSTEM_PROMPT, render_prompt

TITLE = "Oil jumps as Hormuz shipping halts"
TEXT = (
    "Crude oil futures rose after shipping through the Strait of Hormuz halted. "
    "Exxon Mobil (XOM) and Chevron (CVX) gained as tanker rates spiked. "
) * 4

# The full schema a model reply carries; the same shape `tests/test_analysis_cost.py` uses.
REPLY = {
    "relevant": True,
    "verdict": "INVEST",
    "signal_score": 2,
    "confidence": 0.7,
    "reasoning": "Supply risk lifts energy names.",
    "sector_impact": "Energy",
    "tickers": ["XOM"],
    "magnitude": "medium",
    "novelty": "standard",
    "actionability": "high",
    "affected_entities": [{"name": "Exxon Mobil", "ticker": "XOM"}],
    "second_order_effects": [],
    "key_metrics": {},
    "model_name": "example-model",
    "analysis_source": "model",
}


def estimate_tokens(text: str) -> int:
    """Chars/4, the usual planning approximation for English prompts."""
    return max(1, math.ceil(len(text) / 4))


@dataclass(frozen=True)
class Cost:
    input_tokens: int
    output_tokens: int
    per_event_usd: float
    per_1k_events_usd: float
    per_10k_reads_usd: float


def model(
    *,
    input_per_m: float = 0.27,
    output_per_m: float = 1.10,
    repair_rate: float = 0.0,
    read_kb: float = 10.0,
    plan_usd: float = 7.0,
    plan_gb: float = 5.0,
) -> Cost:
    prompt = render_prompt(ANALYSIS_PROMPT, TITLE, TEXT)
    input_tokens = estimate_tokens(SYSTEM_PROMPT) + estimate_tokens(prompt)
    output_tokens = estimate_tokens(json.dumps(REPLY, separators=(",", ":")))
    multiplier = 1.0 + repair_rate
    per_event = (
        (input_tokens * input_per_m + output_tokens * output_per_m)
        / 1_000_000
        * multiplier
    )
    # Reads never call the model; their only marginal cost is the bandwidth of the
    # response on the API plan. 10,000 reads at 10 KB is 0.1 GB of the 5 GB Starter plan.
    reads_gb = 10_000 * read_kb * 1000 / 1_000_000_000
    return Cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        per_event_usd=round(per_event, 6),
        per_1k_events_usd=round(per_event * 1_000, 2),
        per_10k_reads_usd=round(plan_usd * reads_gb / plan_gb, 2),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-per-m", type=float, default=0.27)
    parser.add_argument("--output-per-m", type=float, default=1.10)
    parser.add_argument("--repair-rate", type=float, default=0.0)
    parser.add_argument("--read-kb", type=float, default=10.0)
    parser.add_argument("--plan-usd", type=float, default=7.0)
    parser.add_argument("--plan-gb", type=float, default=5.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    cost = model(
        input_per_m=args.input_per_m,
        output_per_m=args.output_per_m,
        repair_rate=args.repair_rate,
        read_kb=args.read_kb,
        plan_usd=args.plan_usd,
        plan_gb=args.plan_gb,
    )
    if args.json:
        print(json.dumps(cost.__dict__, indent=2))
        return 0

    print(
        f"tokens per analysed event: {cost.input_tokens} input + {cost.output_tokens} output"
    )
    print(
        f"at ${args.input_per_m:.2f}/M input and ${args.output_per_m:.2f}/M output, "
        f"repair rate {args.repair_rate:.0%}:"
    )
    print(f"  per event:            ${cost.per_event_usd:.6f}")
    print(f"  per 1,000 events:     ${cost.per_1k_events_usd:.2f}")
    print(
        f"  per 10,000 API reads: ${cost.per_10k_reads_usd:.2f} "
        f"(at {args.read_kb:.0f} KB each on ${args.plan_usd:.0f}/{args.plan_gb:.0f} GB)"
    )
    print("Free-tier marginal cost for both is $0 while the included quotas hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
