# WorldFin — Deployment & API

The API (`server/`) and the ingest worker (`worker/`) share one Postgres database;
the SPA (`web/`) talks only to the API.

## 1. Local (this machine) — Postgres + Ollama

```bash
python -m server.main              # API on :8010
python -m worker.main --once       # one ingest cycle
npm --prefix web run dev           # dashboard on :8080
```

AI runs on local Ollama (`qwen2.5:7b` analysis, `nomic-embed-text` dedup):
`ollama serve`, then dev mode on (`main.py devtools on`). $0/month.

## 2. Cloud AI

Any OpenAI-compatible provider. Two ways:

- **Dev mode**: `main.py devtools set ai openrouter --field api_key=sk-or-...`
  (or provider `openai`, base_url `https://api.openai.com/v1`, model `gpt-4o-mini`)
- **Env**: `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `FINSCRAPE_MODEL`

## 3. Deployed

`Dockerfile.api` and `Dockerfile.worker` build the two processes; the scheduled
`ingest` workflow runs one worker cycle against the hosted database without an
always-on worker. Set `WORLDFIN_ENV=production`, a real `FINSCRAPE_API_KEY` and
`WORLDFIN_CORS_ORIGINS`, or the API refuses to start.

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
| `GET /api/accuracy` · `/api/sentiment` · `/api/portfolio` | tracking panels | ✅ | ✅ |
| `GET /api/correlations` | cross-source signals | ✅ (local heuristic) | ✅ (pipeline tables) |
| `GET/POST /api/alerts/rules` | alert rules, fired by the worker on new events | ✅ | ✅ `routes/alerts.py` |
| `WS /ws` | realtime event push | ✅ | ✅ |

Production deploy = Render (API from `server/`) + Cloudflare Pages (`web/dist`)
+ Neon Postgres + GitHub Actions worker — see README. The new routes ship
automatically with the `server/` deploy; no SPA rebuild needed beyond `npm run build`.
