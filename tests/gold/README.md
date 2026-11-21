# Gold set (plan M2.1)

`sector_set.jsonl` is the frozen benchmark every model, prompt or extraction change is
scored against. One JSON object per line:

| Field | Meaning |
|---|---|
| `id` | 1-based, stable. Never renumber — a renumber invalidates every stored run. |
| `subject` | The headline, verbatim, lowercased as it arrived. |
| `sector` | The correct sector, one of the eleven the product uses (energy, technology, financials, industrials, materials, healthcare, consumer, utilities, real_estate, communications, other). |
| `verdict` | INVEST / PULL_OUT / OBSERVE, or `null` when the case carries no direction label. |
| `reason` | Why the label is what it is, in one clause. This is the audit trail. |
| `provenance` | Where the case came from. |

## Provenance

* **Cases 1–56 (`model-choice 2026-09-29`)** are the set the DEPLOY.md model table was
  measured on. Those numbers (`qwen3.8-flash:free` 79.5% sector, `mimo-v2.6-flash:free`
  66.7%, `deepseek-v4.1-flash:free` 67.4%) were quoted in the docs with no way to
  reproduce them; this file is that missing artefact. Verdict labels were added on
  2026-11-24 under the rubric below, so a model switch can be judged on direction as well
  as sector.
* **Cases 57–243 (`production subjects 2026-06..09`)** are real event subjects from the
  live corpus. They carry a sector label only. They are here because a benchmark made of
  headlines someone invented measures the inventor, not the model.
* Sector labels were written from the headline alone and reviewed against the house rules
  in `scripts/laya_train/daily.py` (the same rules Laya's training data is built with).

## Verdict rubric

The label is the direction the story implies for the sector/tickers it names, over the
scoring windows (next session, +2 and +4 trading days vs SPY):

* **INVEST** — the story implies upside: demand, pricing power, a supply restriction, a
  contract win, an analyst upgrade, a bullish catalyst.
* **PULL_OUT** — the story implies downside: demand destruction, a price collapse, costs
  rising faster than they can be passed on, a supply glut, an analyst downgrade.
* **OBSERVE** — no clear directional edge: politics without a sector consequence, a past
  move already banked, a procedural item, an unresolved event.

A direction call must be justified by something in the headline itself. "Tariff policy"
with no named measure is OBSERVE; "sanctions on Russian refineries" is INVEST for energy
because supply is being restricted.

## How to use it

```bash
# Live measurement against a real endpoint (needs FINSCRAPE_MODEL / OPENAI_* set):
python -m scripts.eval_model --model deepseek-v4.1-flash:free --prompt v1

# Deterministic, offline, no network — the CI gate:
python -m scripts.eval_model --replay tests/gold/recordings/heuristic-baseline.jsonl --gate
```

Rules for changing this file:

1. **Never edit an existing label to make a run pass.** If a label is wrong, fix it in its
   own commit with the reason, and re-record every stored run in `docs/EVAL.md`.
2. **Appending is cheap, deleting is not.** A new case goes at the end with the next id.
3. An unlabelled verdict (`null`) is honest; a guessed one is not.
