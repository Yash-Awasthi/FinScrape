# WorldFin Frontend — Design

*The design system for the WorldFin SPA (`web/`), including the live market feed.*

## Principles

1. **Terminal, not dashboard** — dense, dark, monospace numerals; every pixel is data.
2. **One screen per mental mode** — variants switch the panel set, never the frame.
3. **Same-origin data** — the SPA calls `/api/*` and `/ws` relative to its host; it
   doesn't know or care whether the backend is the production server (Postgres) or
   the local dev server (SQLite + live quotes).
4. **Realtime where cheap, polled where honest** — events stream over WebSocket;
   quotes poll every 15s (honest about upstream rate limits, still "live" to a human).

## Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ WorldFin   [World][Finance][News Lobby][Markets Live]   12:34:56 ● ↻ │  header
│ ▲NVDA 230.36 +0.32% · ▼TCS 2304 -0.69% · ▲600519.SS 1330 +2.40% …    │  ticker tape (always on)
├──────────────────────────────────────────────────────────────────────┤
│  ┌ panel ──┐ ┌ panel ────────────┐ ┌ panel ──┐                       │
│  │         │ │                   │ │         │   12-col grid,        │
│  └─────────┘ └───────────────────┘ └─────────┘   draggable rows        │
└──────────────────────────────────────────────────────────────────────┘
```

- **Ticker tape** (global, under header): live quotes scrolling; ▲ green / ▼ red;
  pauses on hover; each symbol links to filtering the signal feed.
- **Panels** are the unit of composition — each has `id`, grid position, and a
  `load()` (pull-once) or `update()` (push-on-store-change) path.

## Variants (panel sets)

| Variant | Purpose | Panels |
|---|---|---|
| **World** | geopolitical events | feed, globe, stats, correlations, worldnews, livetv, calendar, accuracy |
| **Finance** | equity intelligence | feed, globe, stats, markets, suggestions, correlations, accuracy, calendar, sentiment |
| **News Lobby** | the news room | lobby (tabbed multi-feed), stats, suggestions, globe, signal-feed |
| **Markets Live** | the trading tape | markets-live (quote cards by region), watchlist, stats, globe, suggestions |

## Live market feed (design)

- **Source of truth**: `finscrape/exchanges.py` — 28 exchanges; China A-shares via
  keyless Eastmoney→Sina native adapters, everything else via Yahoo Finance.
- **Endpoint**: `GET /api/quotes?symbols=AAPL,RELIANCE.NS,600519.SS` — symbols carry
  their Yahoo suffix (the suffix *is* the exchange tag); bare = US.
- **Refresh**: 15s poll while the Markets Live variant (or tape) is visible.
- **Watchlist**: user's symbols in `localStorage`, add/remove inline, same feed.
- **Cards** grouped by region (Americas / Asia / Europe / MEA) with currency + source
  badge (sina / eastmoney / yahoo) so data provenance is always visible.
- Failure posture: a dead upstream removes nothing — the card shows the last known
  price with a stale marker. Never blank the screen on a network blip.

## Backend modes (same SPA, same contract)

| | Production (`server/`) | Local (`finscrape/serve.py`) |
|---|---|---|
| DB | Neon Postgres (asyncpg) | SQLite (`data/finscrape.db`) |
| Events/suggestions | SQL over Postgres | SQL over SQLite, same shapes |
| Quotes | same `exchanges.py` layer | same layer |
| Static | Cloudflare Pages / nginx | FastAPI serves `web/dist` |
| Run | Render / docker | `python main.py serve --port 8080` |

Run the whole thing locally: `npm --prefix web run build`, then
`python main.py serve` → **http://localhost:8080**.
