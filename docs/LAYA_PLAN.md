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
   Result (3 Oct 2026, `python -m scripts.backfill.sector_contest`): test 3,000 uniform from
   128,618 single-company events, no-company 1,000. Every LoRA and the embeddings beat the
   old no-model chain (15.7%) by far, the LoRA reaching 95.6% against frozen Laya's 56.0%,
   but almost all of that was company-name memory (99.9% on companies seen 100+ times in
   training, 52.6% on unseen ones), and on 500 live headlines both LoRAs read macro stories
   worse than frozen (tanker strikes as industrials, or `other`). The truth is a name match,
   so a name match settles it: the pipeline now matches S&P 500 short names in the headline
   (`finscrape/analysis/sp500.py`), and a named company outranks Laya, which was wrong 389
   times to 33 there. All chains then tie at 78.2% on test (96.0% in the production
   taxonomy, which files GOOGL, AMZN and META under technology), so the keep rule cannot
   separate them; frozen Laya stays for stories naming no company, where it labels 13% of
   live headlines that would otherwise stay `other`. No LoRA was published.
6. **Call tuning.** On live events, fit INVEST and PULL_OUT score thresholds and weights
   per source and event type on the older half, test on the newer half. Kept only under the
   calls keep rule.
   Result (3 Oct 2026, `python -m scripts.backfill.call_tuning report`): 2,949 scored live
   events, older half 23 Jun to 9 Jul (6-day purge before the 15 Jul cut), newer half 15 Jul
   to 30 Sep; no live data from 2 Aug to 21 Sep. The fit chose +/-2 thresholds and muted
   `regulatory_decision`; all source weights stayed 1. On the newer half the current +/-3
   rule hit 50.6% of 243 at +2 days and 68.3% of 186 at +4 (Wilson 61.3% to 74.5%); the
   tuned rule 50.8% of 620 and 62.9% of 399. Neither clears the keep rule at +2, both do at
   +4, and tuning doubles the calls for 5.4 fewer points, so production keeps +/-3 and
   weight 1 (owner decision). Calls cluster on the same days (busiest test day 42 current
   calls, 130 tuned), so the intervals are too narrow, and the current rule swung from
   46.7% at +4 on the older half to 68.3% on the newer.
7. **Bandit shadow.** Contextual bandit, actions INVEST / PULL_OUT / OBSERVE, reward the
   +4 day excess return over SPY (OBSERVE earns 0). Features: CAMEO code, QuadClass,
   Goldstein scale, mentions, average tone; sector and country; the ticker's excess return
   over the prior 5 and 20 days and ATR%; source domain, weekday, hours before the close.
   Trained on the backfill train split, checked on the test split, then logs its own call
   beside every live call. It takes over only when it beats the tuned rules on the same
   test weeks and clears the calls keep rule.
   Offline result (3 Oct 2026, `python -m scripts.backfill.bandit`): 335,236 train and
   127,101 test single-company events (1 Oct 2025 to 28 Sep 2026, 249 trading days). One ridge
   regression on ex4 (the per-action linear models collapse to it, since every action's
   reward is known offline), 355 features, strength and call rate picked on Jul to Sep 2025.
   It fits train (correlation 0.11) and finds nothing on test (0.0002): its 61,969 calls hit
   48.7% at +2 and 48.9% at +4, -3.2 bp a call. Always PULL_OUT hit 51.8% and 52.9% (+8.9 bp,
   Wilson above 50%), always INVEST 47.1% at +4, the best tone rule (tone >= 1 or <= -1)
   50.3% and 49.8%. Per ticker and day the bandit is 50.2% of 15,018. Always PULL_OUT wins
   because news-named S&P 500 stocks lagged SPY in the test year, not because of the news.
   Calls land on every test day (busiest 589), so event-level intervals are far too narrow.
   The bandit fails the keep rule and loses to a baseline, so it was dropped (owner
   decision, 3 Oct): no shadow logging, live calls stay on the +/-3 score rule.
8. **Weekly job.** Every Saturday, score live events whose +2 and +4 day windows have
   closed, and append the week's GDELT events and outcomes to the backfill.
   Done (3 Oct 2026): the `score-week` Action (`python -m worker.score_week`, Saturdays
   06:00 UTC) scores live calls up to a year old whose windows closed, since ingest only
   reaches back 30 days, and prints the +2 / +4 day rates of the last two weeks and of all
   calls. The Windows task `WorldFin backfill weekly` (Saturdays 10:00 local,
   `python -m scripts.backfill.weekly`, log in `data/backfill/weekly.log`) refreshes prices,
   rebuilds the months the last 8 days touched and recomputes `outcomes.parquet`.

Also in step 4: remove the direction veto, with a test that a confident opposite
direction no longer marks an event as divergent.

## Next session

All steps are done. Watch the first Saturday runs of both weekly jobs.
