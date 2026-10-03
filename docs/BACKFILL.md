# Backfill and call scoring

How WorldFin judges its sector labels and its INVEST / PULL_OUT calls. Market data and
official company sectors are the only judges: no hand labels, no teacher labels.

## Rules

| topic | rule |
|---|---|
| sector truth | a headline naming exactly one S&P 500 company carries that company's GICS sector |
| hit | INVEST hits when the ticker beats SPY, PULL_OUT when it lags SPY, over +2 and +4 trading days |
| outcome base | last close before the news; news after 16:00 ET or on a closed day uses that close |
| universe | current S&P 500 constituents (survivorship bias accepted) |
| time split | fit on 2023-10-01 to 2025-09-30, test from 2025-10-01; never a random split |
| keep rule, sector | beat the no-model chain by 5 points on the test split, test n >= 1,000 |
| keep rule, calls | Wilson 95% interval of the test hit rate entirely above 50% |
| GPU | runs started by hand only |

Live calls come from the LLM's `signal_score`. The backfill never runs the LLM, because
the model may already know how those weeks ended, so call thresholds are tuned on live
events only, and backfill studies use features that need no LLM.

## Data

Local Parquet under `data/backfill/`, gitignored. Nothing goes to Supabase except the live
scores.

| file | columns |
|---|---|
| `universe.parquet` | ticker, name, gics_sector, sector, aliases |
| `prices.parquet` | date, ticker, close (adjusted), including SPY |
| `events/YYYY-MM.parquet` | event_id, added_utc, url, domain, title (slug), cameo, quad_class, goldstein, mentions, avg_tone, country, lat, lon, tickers, n_companies |
| `outcomes.parquet` | event_id, ticker, base_date, ret2, ret4, spy2, spy4, ex2, ex4 |

GICS to taxonomy: Information Technology -> technology, Health Care -> healthcare,
Financials -> financials, Energy -> energy, Consumer Discretionary and Consumer Staples ->
consumer, Industrials -> industrials, Materials -> materials, Utilities -> utilities,
Real Estate -> real_estate, Communication Services -> communications.

News is the GDELT 2.0 15-minute events export, whose DATEADDED gives the time of day the
outcome base needs. Titles are URL slugs; companies are matched on the universe's names and
aliases; events are deduplicated by URL.

Build from scratch, in order:

```
python -m scripts.backfill.universe        # universe and 3 years of closes
python -m scripts.backfill.gdelt_month YYYY-MM   # once per month from 2023-10
python -m scripts.backfill.outcomes
```

Facts about the data (3 Oct 2026): 503 tickers, 773 trading days; 37 months, 25.9M events,
about 466,000 naming exactly one company, 99.6% of those with a +4 day outcome; about
3.7 GB. GDELT published nothing from 15 Jun to early Jul 2025, so 2025-06 holds about
5,500 single-company events against 9,400 to 17,400 in other months, and the monthly yield
falls from about 15,000 in 2024 to about 9,500 in 2026. Names that read as plain words
(intel, southern, eaton, rtx, workday) only match in fuller form, so INTC, WM, DD and CMI
get no matches. Corteva's 1 Oct 2026 spin-off was not price-adjusted when pulled; its
windows across that date are dropped (`UNADJUSTED` in `outcomes.py`).

## Weekly jobs

- `score-week` Action, Saturdays 06:00 UTC via the cron Worker (`python -m worker.score_week`): scores live
  calls up to a year old whose windows have closed (ingest only reaches back 30 days) and
  prints the +2 / +4 day rates of the last two weeks and of all calls.
- Windows task `WorldFin backfill weekly`, Saturdays 10:00 local
  (`python -m scripts.backfill.weekly`, log in `data/backfill/weekly.log`): refreshes
  prices, rebuilds the months the last 8 days touched and recomputes outcomes. It refuses a
  short prices download rather than overwrite history.

## Results

Each study reruns with its script.

- **Sector contest** (`scripts.backfill.sector_contest`): on 3,000 test single-company
  events, LoRAs reached 95.6% against frozen Laya's 56.0% and the old no-model chain's
  15.7%, almost all from memorised company names (52.6% on companies unseen in training),
  and they read live macro stories worse than frozen Laya. A name match is the truth, so
  the pipeline now matches S&P 500 short names in headlines (`finscrape/analysis/sp500.py`)
  ahead of Laya; all chains then tie at 96.0% in the production taxonomy. Frozen
  `laya-20261001-1041` stays for stories naming no company, where it labels 13% of live
  headlines that would otherwise stay `other`. No LoRA was published.
- **Call tuning** (`scripts.backfill.call_tuning`): on 2,949 scored live events, the rule
  fit on 23 Jun to 9 Jul (+/-2) hit 62.9% of 399 at +4 days on 15 Jul to 30 Sep against the
  current +/-3 rule's 68.3% of 186. Neither clears the keep rule at +2 days, so production
  keeps +/-3 with every source weighted 1.
- **Bandit** (`scripts.backfill.bandit`): a ridge model on GDELT, sector, price and timing
  features fit train (correlation 0.11) and found nothing on 127,101 test events (0.0002):
  48.9% at +4 days. Always PULL_OUT hit 52.9%, because news-named S&P 500 stocks lagged SPY
  in the test year. The bandit was dropped.

Calls cluster on the same days (the busiest test day held 589 bandit calls, 42 live
calls), so every interval above is narrower than the data supports.
