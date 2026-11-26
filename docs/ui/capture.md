# Re-capturing the before-images

The dashboard needs `/api` and a database, neither of which is available in this
environment. `serve.cjs` serves the real `web/dist` bundle and answers the REST calls with
fixtures shaped after `web/src/api.ts`. `capture.cjs` drives Chromium through Playwright and
writes viewport screenshots to `before/`.

## Run

```bash
cd web && npm run build          # dist/ is what the server serves
cd .. && node docs/ui/capture.cjs    # 27 PNGs into docs/ui/before/
node docs/ui/verify-widths.cjs       # IHDR width + non-blank check
```

`capture.cjs` starts `serve.cjs` in-process on `127.0.0.1:8099` and stops it when done.
Chrome comes from `CHROME_BIN` or the Playwright cache at
`C:/Users/Yash/AppData/Local/ms-playwright/chromium-1255/chrome-win64/chrome.exe`.

## Changing the fixtures

All JSON lives at the top of `serve.cjs`: `EVENTS` (9 rows, four verdicts, six tickers and
sectors), `SCENARIOS` (s1–s3), `ACCURACY`, `OUTCOMES`, `RELIABILITY`, `HEALTH`,
`CORRELATIONS`, `SUGGESTIONS`, `QUOTES`, `CANDLES`, plus `predictionFor()` and the council /
analysis stubs. Timestamps are computed from the capture time (`at(minutesAgo)`), so
"2m ago" stays true whenever the set is regenerated.

Routes answered: `/api/events`, `/api/events/:id`, `/api/stats`, `/api/dates`,
`/api/sectors`, `/api/watchlists`, `/api/watchlists/1/feed`, `/api/storylines`,
`/api/scenarios`, `/api/scenarios/:id`, `/api/correlations`, `/api/health`, `/api/feeds`,
`/api/suggestions`, `/api/accuracy`, `/api/outcomes`, `/api/candles`, `/api/market/quotes`,
`/api/predict/:id`, `/api/reliability`, `/api/ai/council`, `/api/ai/analyze`.

## Capture rules

- Widths 360x800, 768x900, 1440x900; `fullPage: false` because the spec fixes the width.
- Off-origin requests are aborted, so Google Fonts and the globe texture never load. The
  globe canvas draws but has no earth texture in these images.
- The WebSocket is mocked with the same event rows; no backend is contacted.
- My Desk renders its empty state on a fresh profile, so the capture dispatches the app's
  own `worldfin:followed` event (what a successful follow does) to load the fixture list.
  Positions are seeded in `localStorage` for the exposure panel.
- The `ticker` surface is `#tickers` scrolled to `[data-id="candles"]`, the chart-focused
  render. `council` selects the first feed row and waits for the stub's consensus text
  before the shot.
