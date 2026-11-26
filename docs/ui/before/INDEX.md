# Dashboard before-images

Real renders of the built SPA from the worktree at `f7aa607` (other in-flight `web/src`
edits included, since the build serves the worktree), captured 2026-11-26. Each image is a
viewport screenshot (not full page): the spec fixes the width, and page heights differ by
view. Off-origin requests (Google Fonts, the globe texture CDN) are aborted, so the set is
offline-stable.

Chrome: `C:/Users/Yash/AppData/Local/ms-playwright/chromium-1255/chrome-win64/chrome.exe`,
launched by Playwright. Server: `docs/ui/serve.cjs` (fixtures shaped after `web/src/api.ts`,
serving `web/dist`). Capture command for every row: `node docs/ui/capture.cjs` (run after
`cd web && npm run build`). Widths are checked by reading each PNG's IHDR:
`node docs/ui/verify-widths.cjs` prints `27 PNGs, 0 failed`.

| View | Width | Route / URL | Fixture notes | Command | Date |
| --- | --- | --- | --- | --- | --- |
| landing | 360 | `/` | `/api/stats`, `/api/feeds`, `/api/accuracy`, `/api/events?limit=60`; hero globe texture is off-origin and blocked, so only the frame shows | `node docs/ui/capture.cjs` | 2026-11-26 |
| landing | 768 | `/` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| landing | 1440 | `/` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| today | 360 | `/app/#today` | 9 events, 3 scenarios, 2 storylines, stats, dates, 4 correlations, 8 suggestions | `node docs/ui/capture.cjs` | 2026-11-26 |
| today | 768 | `/app/#today` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| today | 1440 | `/app/#today` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| desk | 360 | `/app/#desk` | `/api/watchlists` + `/api/watchlists/1/feed`; panel load fired with the app's own `worldfin:followed` event (a fresh browser has no session write); positions XOM/FRO/NVDA seeded in localStorage | `node docs/ui/capture.cjs` | 2026-11-26 |
| desk | 768 | `/app/#desk` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| desk | 1440 | `/app/#desk` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| ticker | 360 | `/app/#tickers` scrolled to `[data-id="candles"]` | chart-focused Tickers surface; `/api/candles?symbol=XOM` (30 daily candles), `/api/suggestions` | `node docs/ui/capture.cjs` | 2026-11-26 |
| ticker | 768 | `/app/#tickers` scrolled to `[data-id="candles"]` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| ticker | 1440 | `/app/#tickers` scrolled to `[data-id="candles"]` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| record | 360 | `/app/#record` | `/api/accuracy` (84 scored, 52 hits, vs-SPY d2/d4), `/api/reliability`, `/api/predict/:id`, 11 outcomes | `node docs/ui/capture.cjs` | 2026-11-26 |
| record | 768 | `/app/#record` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| record | 1440 | `/app/#record` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| sources | 360 | `/app/#sources` | `/api/health` (11 sources, 1 WARN / 1 STALE / 1 EMPTY), `/api/correlations` (4 signals) | `node docs/ui/capture.cjs` | 2026-11-26 |
| sources | 768 | `/app/#sources` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| sources | 1440 | `/app/#sources` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| event | 360 | `/app/#/app/event/1` | `/api/events/1` (full row: sources, excerpt, sector chain, tickers, corroboration); no `score_trace`, so the page says none was returned | `node docs/ui/capture.cjs` | 2026-11-26 |
| event | 768 | `/app/#/app/event/1` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| event | 1440 | `/app/#/app/event/1` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| scenario | 360 | `/app/#/app/scenario/s1` | `/api/scenarios/s1` (3 members, 4-point history, window 240/400 over 7 days) | `node docs/ui/capture.cjs` | 2026-11-26 |
| scenario | 768 | `/app/#/app/scenario/s1` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| scenario | 1440 | `/app/#/app/scenario/s1` | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| council | 360 | `/app/#today`, first feed row selected, then "Ask the analyst council" | `/api/ai/council?id=1` (CAUTIOUS, 72% agreement, 1 dissent); row selection also loads `/api/predict/1` and `/api/outcomes` | `node docs/ui/capture.cjs` | 2026-11-26 |
| council | 768 | `/app/#today`, same interaction | same | `node docs/ui/capture.cjs` | 2026-11-26 |
| council | 1440 | `/app/#today`, same interaction | same | `node docs/ui/capture.cjs` | 2026-11-26 |

## What the images show

- The scenario detail page collapses into the 300 px rail column at 1100 px and wider.
  `.ev-host { display: block }` in `web/src/styles.css` overrides the `hidden`
  attribute, so the hidden event host still occupies the first grid cell and the scenario
  host lands in the rail column. Below 1100 px the media query has one column, so it looks
  normal.
- The globe panel is dark because `globeImageUrl` points at unpkg and the capture blocks
  off-origin requests. The canvas renders; only the earth texture is missing.
- `ticker-*` is the chart-focused Tickers surface (`#tickers` scrolled to the candles
  panel). The row text names nine surfaces (landing, four dashboard views, event, scenario,
  ticker, council) = 27 files; the `tickers` view is the `ticker` file.
