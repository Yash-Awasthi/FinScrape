# WorldFin — API

The API (`server/`) and the ingest worker (`worker/`) share one Postgres database;
the SPA (`web/`) talks only to the API.

Run it locally with `make demo` or the no-Docker steps in the [README](../README.md);
production hosting and operations are in [DEPLOY.md](DEPLOY.md) and [RUNBOOK.md](RUNBOOK.md).
In production (`WORLDFIN_ENV=production`) the API refuses to start without a real
`FINSCRAPE_API_KEY` and explicit `WORLDFIN_CORS_ORIGINS`.

## API surface (view-only — the platform renders intelligence, it never trades)

| Endpoint | Purpose | Local | Production |
|---|---|---|---|
| `GET /api/quotes?symbols=` | live quotes, all markets | ✅ | ✅ `routes/market.py` |
| `GET /api/candles?symbol=&period=&interval=` | OHLCV chart data | ✅ | ✅ `routes/market.py` |
| `GET /api/events` · `/api/stats` · `/api/dates` | stored intelligence | ✅ | ✅ |
| `GET /api/suggestions` | momentum-ranked tickers | ✅ | ✅ (surge multiplier in SQL) |
| `GET /api/predict/{id}` · `/api/reliability` | calibrated probabilities + evidence | ✅ | ✅ `routes/insight.py` |
| `GET /api/scenarios` | clustered events scored into advice (stance, net exposure, instruction) | ✅ | ✅ `routes/insight.py` |
| `GET /api/agents/analyze?ticker=` | multi-agent research commentary | ✅ | ✅ `routes/agents.py` |
| `GET /api/ai/analyze?id=` | per-event LLM reasoning | ✅ | ✅ |
| `GET /api/feeds` · `/api/rss-proxy` | world news feeds | ✅ | ✅ |
| `GET /api/accuracy` · `/api/sentiment` | tracking panels | ✅ | ✅ |
| `GET /api/correlations` | cross-source signals | ✅ (local heuristic) | ✅ (pipeline tables) |
| `POST /api/events` | ingest a batch of analysed events (worker) | ✅ | ✅ |
| `GET/POST /api/alerts/rules` | alert rules, fired by the worker on new events | ✅ | ✅ `routes/alerts.py` |
| `WS /ws` | realtime event push | ✅ | ✅ |

Mutating routes (`POST /api/events`, alert rules, the Telegram webhook) need the
`X-API-Key` header; see [SECURITY.md](SECURITY.md). Full schema at `/docs` on the API.
