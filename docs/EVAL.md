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

## Ticker coverage over 100 headlines (M5.1)

Command: `uv run -p 3.14 --group server --group dev pytest -q tests/test_entity_index.py tests/test_ticker_resolve.py tests/test_grounded_tickers.py`

Headlines are ids 1..100 of `tests/gold/sector_set.jsonl` (the first 100 rows of the 243-case gold set, not a separate corpus). The merged entity index (`finscrape/extract/entity_index.py`, over sector keywords, company aliases, SEC legal names and product names) resolves **51 of 100** headlines to at least one symbol, naming **50 distinct symbols**. The product entries added with the index do not appear in these macro and geopolitics headlines; they widen the vocabulary without moving this number.

The 25-symbol overlap is still the ceiling on what the market bridge prices, but not on what the index can name: 20 of the 50 resolved symbols fall inside `server.correlate._topics_by_ticker()`'s 25 and 30 fall outside. The index names twice as many symbols as the bridge, and this work does not change the bridge itself — widening what is priced still needs that intersection to change.

Precision caveat from the same audit: **11 of those 51** covered headlines resolve through a generic or ambiguous word rather than a named company or product. Examples: id 3 (`BLSH`, from the SEC legal name "bullish" in "da davidson stays bullish"), id 56 (`PFE`, from "drug boats"), id 70 (`LMT`, from "defense wins appeal"), id 98 (`SONY` and `TM`, from "japan" in a Hilton hotel story); the rest are ids 15, 64, 67, 76, 84, 88 and 90 ("central bank", "war on drug cartels", "insurance", an earthquake bulletin naming Russia, "drug boat", "middle east conflict" in a utilities story, and a local Manipur conflict). So 51/100 is a coverage ceiling on which headlines the index can name, not a precision claim, and the market bridge's 25-symbol intersection is unchanged.

## Sector chain: who decided, and per-source accuracy (M5.1)

Command: `uv run -p 3.14 --group server --group dev pytest -q tests/test_sector_chain.py tests/test_sector_eval.py tests/test_laya_sector.py`

`finscrape/signals/sector_chain.py` `decide()` replays `laya.choose_sector` in the same order and name the layer that won: confident Laya with no company named (`laya`), the LLM token after the technology guard (`model`), the keyword detector (`keyword`), the sector of the single company named (`company`), else a plausible Laya label or `other` (`fallback`). Parity on the 243-case gold set is **243/243**: the attributed sector equals `choose_sector`'s on every case, so the labels describe the real chain rather than a parallel one.

The gold run passes `llm_sector=""` for every case, because no LLM sector labels are recorded offline. That is stated here so the attribution distribution cannot be mistaken for a model measurement.

| Source | n | Accuracy |
|---|---|---|
| decided by `keyword` | 102 | 77.5% |
| decided by `company` | 5 | 80.0% |
| decided by `fallback` | 136 | 52.9% |
| decided by `laya` | 0 | n/a |
| decided by `model` | 0 | n/a |
| keyword classifier alone, all cases | 243 | 32.5% |
| company layer alone, cases where it emits | 10 | 90.0% |
| Laya alone, cases where it emits | 0 | UNPROVABLE |
| final chain, all cases | 243 | 63.8% |

Attribution distribution: laya 0, model 0, keyword 102, company 5, fallback 136.

The model layer is UNPROVABLE offline: `tests/gold/recordings/` holds only `keyword-baseline`, a heuristic, and no recorded LLM or Laya sector labels exist. Its accuracy cannot be measured here and no number is claimed. What is measurable is the count of `model` decisions, and on this run it is zero because `llm_sector` is empty for every case; the zero measures the input, not the model.

Two readings worth keeping. The keyword classifier alone scores 32.5% over all 243 because it returns no label on most macro headlines and an empty label counts as a miss; when it is the deciding layer its accuracy is 77.5% on the 102 it wins. The company layer is the sharpest single source at 90.0% of the 10 cases where a named company resolves to an uncontested sector, but it covers 10 of 243 cases.

## Scenario clustering: precision/recall (M5.1)

Command: `.venv/Scripts/python.exe -m pytest -q tests/test_cluster_precision_recall.py`

**20 clusters labelled in-repo from `tests/gold/sector_set.jsonl` (243 headlines: ids 1-56 model-choice 2026-09-29, ids 57-243 production subjects 2026-06..09); labels and rationale in `tests/test_cluster_precision_recall.py`.** No separate cluster-label set existed in the repo, so the labels were written on 2026-11-26 from the headline text and committed with the corpus. They describe the headlines, not the clustering output.

### Rubric

A cluster is one storyline at feed granularity: the same real-world development, or one continuing thread a reader would want collapsed under a single top row. A shared domain is not enough: "every Iran headline", "every defence headline" and "every gold headline" are not clusters. When a headline's membership is uncertain it stays unlabelled (a singleton); a missing label costs recall, a guessed one corrupts precision. Each of the 20 labels names the development and the shared actor, decision or thread that makes it one story.

### Metric

Pairwise over all C(243,2) = 29,403 headline pairs. A pair is positive in gold when both ids sit in the same one of the 20 clusters; positive in the prediction when `cluster_events` puts them in the same cluster. Precision = TP/(TP+FP), recall = TP/(TP+FN). Singletons contribute only true negatives.

Adapter: `same_story`'s word rule (`finscrape/analysis/clusters.py`: at least two shared content words, and at least half the shorter headline) with the shared-ticker gate removed, because no gold headline carries a ticker; threshold `LEXICAL_OVERLAP` 0.5. The 48-hour window is inert because the gold set has no timestamps; window behaviour is covered by `tests/test_clusters.py`, not this corpus. The Ollama embedding path is UNPROVABLE offline: no model and no recorded vectors are committed, so no number is claimed for it.

### Result

| Metric | Value |
|---|---|
| Precision | **0.720** |
| Recall | **0.321** |
| True positives | 18 of 56 gold pairs |
| False positives | 7 |
| False negatives | 38 |
| Predicted clusters | 225 (211 singletons) |
| Corpus | `tests/gold/sector_set.jsonl`, n=243 headlines |
| Labels | 20 clusters, 56 positive pairs |

Reading: the word rule is precise enough that most merges it makes are real storylines, and it recovers only a third of the gold pairs because paraphrases (`ebola deaths top 2000` against `ebola vaccine trial begins`) share few content words. The seven false positives are label-boundary cases: two pairs of crypto "moved N% in 24h" reports merged as one column, two "join the trillion club" market-cap stories merged, two air-traffic-control stories merged, a Trump-tariff headline merged with Canada's response, a Houthi strike merged with Yemen displacement, and two Zelenskyy statements merged. They are reported, not tuned away.

## Hallucination guard over 200 fixtures (M5.1)

Command: `.venv/Scripts/python.exe -m pytest -q tests/test_prompt_guard.py tests/test_grounded_tickers.py tests/test_entity_index.py`

Ids 1..200 of `tests/gold/sector_set.jsonl` (the first 200 rows of the 243-case gold set, not a separate corpus) supply the fixtures. For each subject the merged entity index resolves the symbols the article supports; one real-looking symbol from a fixed pool (HON, ZZZ, QQQ, SPY, IWM, GLD, TLT, XLF, XLE, ARKK) that neither the index nor the text names is then appended, and `ungrounded_tickers` must return exactly that symbol while `assert_grounded` raises naming it. Result: **200/200 fixtures checked, 479 kept tickers, 200 injected hallucinations caught, 0 skipped**.

`finscrape/analysis/prompt_guard.py` also grounds a symbol from `$TSLA`, a bare `TSLA`, `Tesla (TSLA)` and index aliases such as "tesla", while English prose ("price target", "arm wrestlers", uppercase "ALL"/"NOW") grounds nothing. The guard ships as a reusable assertion in `finscrape/analysis/prompt_guard.py`, and because no analysis-pipeline caller wires it yet, wiring it into the analysis pipeline is a separate unit.

## Ablation: the score-calibration caps (M5.2)

Command: `.venv/Scripts/python.exe -m scripts.ablation`

Corpus: `tests/gold/recordings/keyword-baseline.jsonl`, **243 recorded replies** (the deterministic baseline). 24 carry a non-zero `signal_score`; 28 carry all three calibration fields (`magnitude`, `actionability`, `novelty`). The two axes are the rules `finscrape.analysis.validator.score_trace` can switch off on this data: the magnitude cap (`_MAGNITUDE_CAP`, low 2 / medium 3 / high 5) and the novelty rescale (a `rehash` is held at 2). Verdict bands are imported from `scripts.eval_model._verdict_from_score`, so the table uses the shipped thresholds, not a copy.

| Arm | INVEST | OBSERVE | CAUTIOUS | PULL_OUT | Verdict delta | Score changes |
|---|---|---|---|---|---|---|
| cap on x novelty on (shipped) | 1 | 219 | 0 | 23 | 0 | 0 |
| cap off x novelty on | 1 | 219 | 0 | 23 | 0 | 0 |
| cap on x novelty off | 1 | 219 | 0 | 23 | 0 | 0 |
| cap off x novelty off | 1 | 219 | 0 | 23 | 0 | 0 |

**Delta: 0 verdicts and 0 scores move when either rule is removed.** That is the measured result, not a stub. The deterministic baseline never emits a shape either cap binds: no `low` magnitude, no `rehash` novelty, and no absolute score above 4 among the 24 non-zero replies, so every row passes both rules unchanged. The caps only bite on model replies that cluster harder than the rule will allow; the replay we can run offline has none. Recording a model run would give the arm a corpus it can move, and the script takes `--recording` for that.

Thin arms are named, not rounded: INVEST n=1 and CAUTIOUS n=0 are **insufficient sample**; only OBSERVE (n=219) and PULL_OUT (n=23) clear 20.

The pipeline's separate +-2 divergence clamp (`finscrape/pipeline.py`, applied after calibration) is **not** an axis here: recomputing `check_divergence` needs the article text, and the recording stores replies without it. Removing that clamp would therefore measure a guessed divergence flag rather than the recorded run, so it stays out of the table.

## Walk-forward evaluation (M5.2)

Command on a dated set: `python -m scripts.eval_model --gold <dated.jsonl> --replay <recording.jsonl> --walk-forward --frozen-prompts frozen.json`

Mechanism: cases are bucketed by the month of their own `published_at` (or `date`) field. The look-ahead guard is `assert_within_period`: a case dated outside the month it is scored in raises `LookAheadError`, an undated case is refused rather than guessed, and the per-month report prints cases, sector accuracy, JSON validity, verdict agreement, p50/p90 ms and the **prompt fingerprint of that period**. The fingerprint is also written to a ledger, so a later run that scores the same month with different prompt text raises `PromptDrift`: a prompt edit starts a new series instead of silently rescoring an old month.

Fixture proof (dates are test data, not a claim about the headlines): 40 real `tests/gold/sector_set.jsonl` rows copied into a temp file, dated across three months, replayed from the matching recorded replies. The report is one row per month, 14 / 13 / 13 cases, each carrying the same fingerprint `695cff07b00aa419`, and a tampered ledger for 2026-10 is refused with `period 2026-10 was scored with prompt 0000000000000000`. Covered by `tests/test_walk_forward.py` (7 passed).

**mechanism landed, per-month results unprovable on this corpus.** The shipped gold set has no per-case dates: 56 rows carry the single date 2026-09-29 in `provenance`, 187 carry only the range 2026-06..09, and the recording header dates the whole snapshot 2026-11-25. Attaching any of those to a row would be invented data, so the CLI refuses the shipped set with `walk-forward needs dated cases: 243 of 243 carry no date` (exit 2) and no monthly figures are published. A dated corpus is the missing input, not a code change.

**Published on a dated public sample, 2026-11-26.** `scripts/gold_public_sample.py --write`
freezes 80 form 8-K cases over two months from SEC EDGAR full-text search, a US government
work in the public domain: 40 per month, one row per company, sector from the company's SIC
division, verdict `null` because a filing is not a direction call. The manifest records both
query URLs, `retrieved_at 2026-11-26T07:37Z` and the sha256 of the frozen file
(`129ef07a...197186`), and labels it "public sample, not production". The run
`python -m scripts.eval_model --gold tests/gold/public_sample_2026_09_10.jsonl --model
keyword-baseline --walk-forward --frozen-prompts
tests/gold/public_sample_2026_09_10.prompts.json --record
tests/gold/recordings/public_sample_keyword.jsonl` scores 2026-09 at 7.5% sector accuracy
over 40 cases and 2026-10 at 0.0% over 40, 100% JSON validity in both, verdict agreement
n/a (nothing labelled), the same fingerprint `695cff07b00aa419` in both periods, p50 17 ms.
The low sector score is the keyword baseline having no SIC knowledge on template headlines;
what the run proves is the split, not the baseline. `pytest -q
tests/test_gold_public_sample.py tests/test_walk_forward.py` -> 11 passed.


