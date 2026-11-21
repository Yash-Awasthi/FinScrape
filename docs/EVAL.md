# Model evaluation runs

Every model or prompt change is scored on the frozen gold set (`tests/gold/`) before it
ships. `scripts/eval_model.py` is the only writer: it prints the four numbers below and,
with `--append-docs`, appends the run here.

What the columns mean:

* **Sector accuracy** — the reply's sector against the gold label, over all 243 cases. This
  is the number the gate uses.
* **JSON validity** — share of replies that parse *and* satisfy `reply_schema.ModelReply`.
  A model that answers beautifully in prose is worthless to the pipeline.
* **Verdict agreement** — INVEST / PULL_OUT / OBSERVE agreement over the 56 labelled cases
  only (the count is in brackets). The rest of the set carries no direction label, and a
  guessed label would make this column meaningless.
* **Latency p50 / p90** — per call, as measured. The p90 is what a 6-article cycle actually
  pays for on its slowest article.

The gate (`--gate`): a run that drops sector accuracy by more than **5 points** against the
newest stored row for the same model + prompt fails. The `keyword-baseline` row is the
deterministic layer stack, recorded once — it is what a model has to beat, and it is the
row CI compares against offline.

Recording a run for CI (no network, no credentials):

```bash
python -m scripts.eval_model --model keyword-baseline \
    --record tests/gold/recordings/keyword-baseline.jsonl
```

Live run against the configured endpoint:

```bash
FINSCRAPE_MODEL=deepseek-v4.1-flash:free OPENAI_BASE_URL=... OPENAI_API_KEY=... \
    python -m scripts.eval_model --model deepseek-v4.1-flash:free --prompt v1 --append-docs
```

A recording carries a fingerprint of the prompt that produced it. Edit a prompt and the
replay fails until you re-record: silently measuring yesterday's text is the failure mode
this exists to prevent.

| Model | Prompt | Date | Sector accuracy | JSON validity | Verdict agreement | Latency p50 / p90 |
|---|---|---|---|---|---|---|
| keyword-baseline | v1 | 2026-11-24 | 63.8% | 100.0% | 46.4% (56) | 10 / 16 ms |
