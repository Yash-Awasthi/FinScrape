# Sector model and call tuning: plan

Replaces the nightly Laya loop (task.md item 11). That loop could not show it was
improving: train, holdout and gold labels all came from one teacher, the holdout was split
from the pool the LoRA trained on, the test set changed size every run, and the 1 Oct
promotion went through with a validation loss of 1.15 against a training loss of 0.66.

## Goals

1. Better sector labels on events.
2. A higher hit rate on INVEST / PULL_OUT calls.

Market data and official company sectors are the only judges. No hand labels, no
teacher labels.

## Decisions (2 Oct 2026)

| topic | decision |
|---|---|
| sector truth | a headline naming exactly one S&P 500 company is labelled with that company's GICS sector |
| macro stories | no company named: `other` unless the sector is clear |
| Laya's job | sector only; the direction veto (`laya.disagrees` in `pipeline.py`) is removed |
| hit | INVEST hits when the ticker beats SPY, PULL_OUT when it lags SPY, over +2 and +4 trading days |
| outcome base | last close before the news; news after 16:00 ET or on a non-trading day uses that close too |
| universe | current S&P 500 constituents (survivorship bias accepted and stated in reports) |
| storage | local Parquet under `data/backfill/`, gitignored; nothing goes to Supabase except weekly live scores |
| time split | fit on 2023-10-01 to 2025-09-30, test on 2025-10-01 onward; never a random split |
| GPU | only runs started by hand; the `WorldFin Laya daily` task is disabled |
| production | keeps `laya-20261001-1041` frozen until something beats it |
| landing page | shows both hit rates, labelled: next-day raw and +2 / +4 days vs SPY |
| keep rule, sector | beat the no-model chain by 5 points on the test split, test n >= 1,000 |
| keep rule, calls | Wilson 95% interval of the test hit rate entirely above 50% |

## Why calls and backfill are tuned on different data

Live calls come from the LLM's `signal_score`. The backfill runs without the LLM, because
the model may already know how those weeks ended. So:

- Threshold and weight tuning (step 6) uses the live events stored since June 2026. They
  were analysed in real time, before their outcomes existed, so they carry no leakage.
- The backfill feeds the sector contest (step 5) and the bandit (step 7), using features
  that need no LLM.

## Data

GICS to taxonomy: Information Technology -> technology, Health Care -> healthcare,
Financials -> financials, Energy -> energy, Consumer Discretionary and Consumer Staples ->
consumer, Industrials -> industrials, Materials -> materials, Utilities -> utilities,
Real Estate -> real_estate, Communication Services -> communications.

| file | columns |
|---|---|
| `universe.parquet` | ticker, name, gics_sector, sector, aliases |
| `prices.parquet` | date, ticker, close (adjusted), including SPY |
| `events/YYYY-MM.parquet` | event_id, added_utc, url, domain, title (slug), cameo, quad_class, goldstein, mentions, avg_tone, country, lat, lon, tickers, n_companies |
| `outcomes.parquet` | event_id, ticker, base_date, ret2, ret4, spy2, spy4, ex2, ex4 |

News comes from the GDELT 2.0 15-minute events export, the same feed `ingestors/gdelt.py`
reads, because its DATEADDED carries the time of day the outcome base needs. Titles are
URL slugs (`slug_title`); companies are matched against the universe's names and aliases.
Events are deduplicated by URL.

## Steps

Each step ends with a check that can be rerun.

1. **Universe and prices.** Build `universe.parquet` from the public S&P 500 list with GICS
   sectors, and 3 years of daily adjusted closes for every constituent and SPY.
   Done when: about 500 tickers, every one mapped to a taxonomy sector, no ticker missing
   more than 5% of trading days.
2. **Pilot: September 2026.** Download one month of 15-minute exports and build that
   month's events file. The month overlaps live data, so matches can be compared with
   stored events. Report: files, bytes, download time, events, distinct URLs, events
   naming exactly one company, and that count per sector.
   Gate: at least 1,000 single-company events in the month. Below that, pilot GDELT GKG's
   organisations field the same way before scaling.
3. **Full backfill.** October 2023 to now, same pipeline, plus `outcomes.parquet`.
   Done when: every month present, outcome coverage per event reported.
4. **Measuring stick.** Re-score every stored live call with the +2 / +4 day vs-SPY
   metric next to the existing next-day number; the landing page shows both.
5. **Sector contest.** On test-split single-company events, score: no model (LLM output
   where stored, keywords, named companies), Laya frozen, embeddings (`nomic-embed-text`)
   plus logistic regression on CPU, and one Laya LoRA trained on train-split labels by a
   hand-started GPU run. Report overall and per-sector accuracy, and on no-company events
   how often each entry leaves `other` versus picks a sector. The winner replaces
   `laya.classify` if it clears the keep rule; otherwise Laya is removed from the pipeline.
6. **Call tuning.** On live events, fit INVEST and PULL_OUT score thresholds and weights
   per source and event type on the older half, test on the newer half. Kept only under the
   calls keep rule.
7. **Bandit shadow.** Contextual bandit, actions INVEST / PULL_OUT / OBSERVE, reward the
   +4 day excess return over SPY (OBSERVE earns 0). Features: CAMEO code, QuadClass,
   Goldstein scale, mentions, average tone; sector and country; the ticker's excess return
   over the prior 5 and 20 days and ATR%; source domain, weekday, hours before the close.
   Trained on the backfill train split, checked on the test split, then logs its own call
   beside every live call. It takes over only when it beats the tuned rules on the same
   test weeks and clears the calls keep rule.
8. **Weekly job.** Every Saturday, score live events whose +2 and +4 day windows have
   closed, and append the week's GDELT events and outcomes to the backfill.

Also in step 4: remove the direction veto, with a test that a confident opposite
direction no longer marks an event as divergent.

## Next session

Steps 1 and 2, ending with the pilot report and a go / plan-B decision.
