# WorldFin Frontend — Design

*The design of the WorldFin SPA (`web/`).*

## Principles

1. **Only what the analysis produced** — every panel shows a verdict, the evidence behind
   it, or how past verdicts turned out. Generic market widgets (quote boards, TV, raw RSS)
   are out of scope.
2. **One view per question** — four tabs, each answering one question, so nothing has to
   be found by scrolling.
3. **Same-origin data** — the SPA calls `/api/*` and `/ws` relative to its host, or
   `VITE_API_BASE` when hosted apart from the API.
4. **Honest numbers** — every hit rate carries its sample size and a 95% Wilson interval;
   calls that moved less than 1% are named as unscored, not hidden.

## Views

| Tab | Question | Panels |
|---|---|---|
| **Today** | What is happening and what should I do? | scenarios, signal feed, globe, calls by verdict, events per day |
| **Tickers** | Which tickers is the news moving? | tickers in the news, chart with the calls naming the symbol, sector heat |
| **Track record** | Can I trust the calls? | next-day and vs-SPY (+2/+4 days) hit rates, calibration, every scored call |
| **Sources** | Is the input healthy? | source health, correlation signals explained in plain words |

The tab lives in the URL hash (`/app/#record`), so a view can be linked. The inspector
rail sits beside Today and Tickers, where events are picked, and gives its width back on
the other two.

```
┌ WorldFin   Today │ Tickers │ Track record │ Sources        00:10 UTC ● ↻ ┐
├───────────────────────────────────────────────────────────┬───────────────┤
│ Scenarios: probability · instruction · exposed tickers     │ Inspector     │
├──────────────────────┬────────────────────────────────────┤ verdict,      │
│ Signal feed          │ Globe                              │ reasoning,    │
│ filters, age, srcs   │                                    │ entities,     │
├──────────────┬───────┴────────────────────────────────────┤ coverage,     │
│ Calls by     │ Events per day (click a day to load it)    │ outcome,      │
│ verdict      │                                            │ AI + council  │
└──────────────┴────────────────────────────────────────────┴───────────────┘
```

## Layout rules

- `web/src/app/variants.ts` declares each view's panels in order with their column and
  row spans. Every band sums to 12 columns, and every registered panel is in exactly one
  view; `layout.test.ts` asserts both, and the layout warns at runtime otherwise.
- Below 1100px the rail drops under the panels and narrow panels pair up; below 700px
  panels stack in one column at a height taken from their row span.
- Cross-panel actions are window events: `worldfin:select-symbol` opens Tickers on that
  symbol, `worldfin:select-sector` / `worldfin:select-source` filter the feed and open
  Today.

## Backend

One backend: the FastAPI `server/` over Postgres (Supabase in production, docker compose or
a native Postgres locally). Locally, `npm run dev` in `web/` serves the SPA on :8080 and
proxies `/api` to the API on :8010.
