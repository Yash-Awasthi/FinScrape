# Calibration and the track record

What the numbers on the site mean, how they are computed, and where they stop being
evidence. Every figure in `/api/accuracy` and `/api/reliability` is produced by
`finscrape/accuracy.py` (pure maths) through `server/accuracy.py` (queries); this page is
the reader's contract, not a second implementation.

## What a "call" is

An **event** is one analysed news story. A **call** is an event whose verdict is
directional — `INVEST` or `PULL_OUT`. `OBSERVE` and `CAUTIOUS` are recorded but are not
scored as right or wrong, because the product does not claim a direction for them.

A call is **scored** once its window has closed and a price was found:

| Field | Meaning |
|---|---|
| `price_move_pct` | the called-direction move, averaged over the event's tickers, signed so that positive always means "the call's direction won" |
| `correct` | `true` if that move is at least **+1%**, `false` if at most **−1%**, `null` inside the band |
| `ex2` / `ex4` | the same move minus SPY's over 2 and 4 trading days, so a call that merely rode the market does not count as skill |
| `correct2` / `correct4` | `true` when the called direction beat SPY, `false` when it lost, `null` when the window is still open |

The ±1% band exists because a 0.2% move is noise, not a wrong call. It is not a
convenience: widening it inflates the hit rate, and the band is fixed at 1% in
`server/accuracy.py` (`THRESHOLD_PCT`) rather than tuned per report.

## Who is measured

`events.analysis_source` says which judge wrote each row: `model`, `model_repaired`,
`heuristic` (the deterministic keyword fallback) or `laya`. `/api/accuracy` reports
`by_source`, so a keyword row can never borrow the model's record. The backtest excludes
heuristic rows from the headline record entirely (see `backtest()`), and `/api/health`
reports what share of the last 24 hours they are.

## Windows

- **Backtest** (`backtest()`): events from the last 30 days, at least 24 hours old, capped
  at 500 per run, scored once (`accuracy_outcomes` is unique per event).
- **Excess return** (`score_vs_spy()`): needs two trading days of data, so a call is
  written with `correct2 = null` until then. Open windows are excluded from rates, never
  counted as misses.
- **Universe**: only events with at least one ticker. An event with no tradeable
  expression cannot be scored and is not in the denominator.

## What is reported

Every rate carries its sample size and a 95% Wilson score interval:

```json
{"hits": 54, "total": 80, "hit_rate": 0.675,
 "n": 80, "ci95": [0.568, 0.767], "sample": "n=80, 57–77%"}
```

The Wilson interval is used instead of the normal approximation because it never goes below
0 or above 1 and does not collapse to a point on an all-hit streak. `sample` adds
"· wide interval" when `n < 30` or the half-width exceeds 15 points — the honest reading of
"67% accuracy" on twelve calls is "somewhere between 30 and 90".

`calibration()` adds:

| Key | Meaning |
|---|---|
| `n` | scored calls the calibration is based on |
| `brier` | mean squared error of stated confidence against outcome; lower is better, 0.25 is a coin flip at 50% |
| `brier_decomposition` | Murphy decomposition: `reliability − resolution + uncertainty = brier`, to rounding |
| `base_rate` | the share of calls that simply came true; a model that always says this rate earns `uncertainty` and nothing else |
| `reliability_curve` | per confidence bucket: mean stated confidence, realised hit rate, and the gap |

`reliability` is the part of the score the model controls (says 90%, delivers 60% → large).
`resolution` is the part its calls earn (daring to say 20% when something is unlikely).
A model can lower its Brier score by never being confident; `resolution` is reported beside
`reliability` so that degenerate strategy is visible.

## Exclusions

- Heuristic (keyword-fallback) rows: excluded from the headline record, reported separately.
- Rows inside the ±1% band: counted in `total`, not in `hits` or `scored`.
- Tickers with no price data in the window: excluded from the mean, and an event with no
  prices at all is skipped rather than scored as a miss.
- Anything older than the 30-day window: out of the score, still visible in the feed.

## Honesty rules

1. No rate is shown without `n` and an interval.
2. No bar or percentage is rendered for a bucket with `n = 0`; it says "no outcomes yet".
3. A hit rate on fewer than 30 calls is labelled "wide interval" wherever it appears.
4. A directional claim ("there is a 72% chance this rises") is never made from a hit rate;
   the calibration panel shows whether stated confidence has historically matched outcomes,
   which is the only claim the data supports.

## Source weighting: a small prior (M5.1)

A source's 90-day hit rate is evidence about the source, not about the event in front of
you, so it enters `score_scenario` as one bounded multiplier per member:
`weight = event_weight(member) * prior(source)`. It can tilt a scenario; it cannot veto one.

`hit_rates(outcomes, now=None, days=90)` returns per source `{n, hits, rate}`. Only rows
whose `checked_at` parses and falls inside the window count. A row with no (or an
unparseable) `checked_at` is excluded: the window cannot place it on the timeline, and
assuming it is fresh would let an undated row vote. `outcome == "correct"` is a hit; any
other value counts in `n` only, the same convention `reliability_tables` uses.

`prior(stats, min_n=10)` shrinks the rate toward a coin flip and maps it onto a weight:

    rate_shrunk = (hits + 5 * 0.5) / (n + 5)
    prior       = clamp(1 + 0.3 * (2 * rate_shrunk - 1), 0.85, 1.15)

Below 10 outcomes the answer is exactly 1.0: thin data moves nothing. The rails are hard,
so the worst and best recorded source differ by at most 1.35x (0.85 vs 1.15). A 60%-hit
source at n=100 earns 1.057, about +6%: the record nudges its members and never overrides
them. Every scenario carries the applied map as `source_priors`, so the tilt can be
audited after the fact.

Measured in `tests/test_source_weights.py`: at n=50 a 10%-hit source gets 0.85 and a
90%-hit source gets 1.15; at n=100 a 60%-hit source gets 1.057. One bad-source member
saying up (p=0.9) against one good-source member saying down (p=0.1) scores tilt -0.120,
probability 0.56, direction down. The prior cannot stop better evidence from being
outnumbered: five bad-source members against one good-source member still score up
(tilt 0.459, probability 0.73), which is the documented limit.
