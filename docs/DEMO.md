# WorldFin demo script

About eight minutes. WorldFin reads world news, decides which tickers and sectors
each story moves, and keeps score of whether its calls came true.

Live: landing https://winfin.pages.dev, dashboard https://winfin.pages.dev/app/.
Open the API health page (https://winfin-api.onrender.com/health) a minute before
you start: the free Render instance sleeps after 15 idle minutes and takes 30-50 s
to wake. Offline, `make demo` serves the same dashboard on a seeded dataset (see
the README quickstart).

## 1. Landing page (1 min)

- The stat band is live: events analysed, feeds watched, and the hit rate.
- Say what the hit rate counts: INVEST and PULL_OUT calls that saw a move of 1% or
  more their way by the next close. OBSERVE and CAUTIOUS make no directional call
  and are not scored.
- The embedded dashboard below is the real one, not a mock-up.

## 2. Scenarios, "what to do about it" (2 min)

- Each card is a recent story turned into an instruction: risk-on or risk-off, which
  sector to add or reduce, and the tickers that carry it (▲ ▼).
- The percentage is the chance the call is right, from the verdict's past record.
- The footer names the sources and says when a call has no scored record yet.
- Click a ticker chip: the chart re-aims to that symbol.

## 3. Signal Feed, Globe and Inspector (2 min)

- The feed is every analysed event, newest first; filter by verdict.
- Press `j` / `k` to walk it. The Inspector on the right shows the reasoning, the
  affected companies with their direction, second-order effects and the sources.
- The globe places the same events; colour is the verdict.

## 4. The proof: Accuracy, Prediction, Source Health (2 min)

- Accuracy: the realized hit rate by verdict and the running equity line.
- Prediction: calibration of stated confidence against outcomes (the dashed line is
  perfect calibration) and per-event odds that say whether they rest on outcomes or
  only on the prior.
- Source Health: every feed with its last fetch; a failing feed shows here instead
  of silently dropping out.

## 5. Context panels (1 min)

Markets Live and the ticker tape, Sector Heat, Suggestions (most-mentioned tickers),
Sentiment (Reddit posts per ticker), News Lobby (raw feeds), Live TV, and Dates
(click a day to filter the feed).

## Honest limits

- The record is young: about 320 scored calls, mostly from June and July, and most
  of them PULL_OUT. Since 29 Sep a PULL_OUT needs a -3 score, mirroring INVEST at +3;
  older calls keep the verdict they were given.
- Ingest runs every 30 minutes on free infrastructure (GitHub Actions dispatched by
  a Cloudflare cron). The dashboard updates on refresh, not by live push.
- The analysis uses free LLMs with a fallback chain. When every model fails, a keyword
  heuristic keeps ingest running; those rows are kept out of scenarios and the record.
- Tickers come from the text and a sector map, so a political story can still carry
  defence or energy names.
- Correlations need several independent sources on one story, so the panel is often
  empty on a quiet day.
- Sentiment reads one Reddit RSS fetch per ingest run; small caps are rarely
  mentioned. Crypto moves cannot be scored against stock prices.
- It is analysis only. Nothing places a trade.
