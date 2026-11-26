# 0002 Free models

## Status

Accepted, 2026-11-26.

## Context

Analysis quality depends on the model that turns headlines into structured calls. Paid frontier models would add a recurring cost the project does not carry, while free-model usage caps are not published, so the choice has to be measured rather than assumed and cheap to reverse.

## Decision

Production runs on TokenHarbor free models through an OpenAI-compatible endpoint: primary `deepseek-v4.1-flash:free`, fallback `mimo-v2.6-flash:free`, the owner's choice on 30 Sep. A full provider outage is still covered because the heuristic path answers when `FINSCRAPE_HEURISTIC_FALLBACK=true`.

The choice is backed by a measurement, not a vendor claim. [DEPLOY.md](../DEPLOY.md) records the comparison run on 29 Sep 2026 against the 56-headline sector gold set with the real analysis prompt:

- qwen3.8-flash:free: 79% valid JSON, 79.5% sector accuracy, p50 30 s.
- mimo-v2.6-flash:free: 96% valid JSON, 66.7% sector accuracy, p50 14 s.
- deepseek-v4.1-flash:free: 77% valid JSON, 67.4% sector accuracy, p50 13 s.

Switching models is gated. The command `python -m scripts.eval_model ... --gate` compares a candidate against the stored baseline on [sector_set.jsonl](../../tests/gold/sector_set.jsonl); a loss of more than 5 points of sector accuracy fails the gate. CI runs `make eval-gate` from the [Makefile](../../Makefile), so the same check runs on every pull request.

## Consequences

Inference costs stay at zero on the free tier, and the fallback chain keeps ingest moving. Quality is whatever the free tier offers and varies by provider, and the free caps are not published, so capacity is not a number the project can plan against.

[COST.md](../COST.md) states that a 429 rotates the key queue and then the heuristic fallback answers, so ingest never stalls. The cost of that resilience is occasional heuristic output in production, which is visible in the data but does not stop the pipeline.

Revisit this decision when free caps can no longer carry the load, or when the 5-point quality floor can no longer be met by an available free model. The gate and the stored baseline are the mechanism for detecting the second case.

## Evidence

- [DEPLOY.md](../DEPLOY.md), "Choosing the model": the three-model comparison and its date.
- [eval_model.py](../../scripts/eval_model.py): the gate used for any model switch.
- [sector_set.jsonl](../../tests/gold/sector_set.jsonl): the 56-headline sector gold set.
- [COST.md](../COST.md): unpublished free caps, 429 key rotation, heuristic fallback.
- [Makefile](../../Makefile): `make eval-gate` in CI.
