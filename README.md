# 🌐 WorldFin — Geopolitical Market Advisory

> **See what moves markets — before it's news.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB.svg)](https://python.org)
[![Cost](https://img.shields.io/badge/Cost-$0%2Fmonth-brightgreen.svg)](docs/DEPLOY.md)
[![Live](https://img.shields.io/badge/Live-Dashboard-blue.svg)](https://winfin.pages.dev/app/)

WorldFin reads world and geopolitical news every 30 minutes, works out which sectors
and tickers each event moves, turns related events into scenarios with a calibrated
probability and an instruction (invest, pull out, observe), and scores every call
against the market move that followed.

**Live:** [landing](https://winfin.pages.dev) · [dashboard](https://winfin.pages.dev/app/) ·
[API docs](https://winfin-api.onrender.com/docs)

---

## ✨ What it does

| | |
|---|---|
| 🌍 **Live globe and feed** | Every event geolocated and coloured by verdict (INVEST / PULL_OUT / OBSERVE / CAUTIOUS) |
| 🧭 **Scenarios** | Related events clustered into scenarios with probability, sector tilt and exposed tickers (`/api/scenarios`) |
| 🎯 **Sectors and tickers** | Sector from a chain of Laya (a small fine-tuned classifier), the LLM and keywords; tickers only when the article backs them |
| 📊 **Track record** | Every call re-scored against the window after the event: hit rate by verdict, reliability, Brier score (`/api/accuracy`) |
| 🔗 **Correlations** | Fires when independent source types corroborate one story |
| 🤖 **Council** | Optional analyst personas debate an event; a judge reads the transcript (`/api/ai/council`) |
| 💬 **Sentiment, alerts** | Reddit posts per ticker, Telegram alerts, alert rules |
| 🏥 **Source health** | Per-source and per-feed freshness, shown on the dashboard |

Sources: 32 world RSS feeds, the GDELT 15-minute events export, USGS earthquakes and
ReliefWeb disasters, all keyless ([docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)).

---

## 🚀 Quick start

Needs Docker and git. No LLM key is required: the demo loads a seeded dataset, and
the worker falls back to keyword analysis until a model is configured.

```bash
git clone https://github.com/Yash-Awasthi/fin-scrape.git && cd fin-scrape
cp .env.example .env
make demo                     # build, start postgres + api + worker + web, seed demo data
#   web → http://localhost:8080 (dashboard at /app/)   ·   api → http://localhost:8010/docs
```

Without `make`: `docker compose up -d --build`, then `docker compose exec api python -m server.seed`.
Stop with `make down`; add `-v` to drop the database. Port taken? Set
`WORLDFIN_API_HOST_PORT` (8010) or `WORLDFIN_PG_HOST_PORT` (5433) in `.env`.

To analyse live news, set `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `FINSCRAPE_MODEL` in
`.env` (any OpenAI-compatible endpoint; a host Ollama is `http://host.docker.internal:11434/v1`
from inside compose) and run `docker compose up -d`.

### No Docker?

```bash
uv sync --group server                          # Python 3.13
# point WORLDFIN_DATABASE_URL in .env at a Postgres you run, then:
uv run python -m server.seed                    # optional demo data
uv run python -m server.main                    # API at :8010
uv run python -m worker.main --once             # one ingest cycle
cd web && npm ci && npm run dev                 # dashboard at :8080, proxies /api to :8010
```

[docs/DEMO.md](docs/DEMO.md) is a scripted 5-minute walkthrough;
[docs/LOCAL-READINESS.md](docs/LOCAL-READINESS.md) covers isolated test databases.

---

## 🏗️ How it runs

```
Cloudflare cron Worker ──(every 30 min)──▶ GitHub Action "ingest"
                                              │  fetch → LLM → Laya sector → tickers
                                              │  → dedup/merge → correlate → backtest
                                              ▼
                                      Supabase Postgres ◀── FastAPI on Render ◀── SPA on Cloudflare Pages
```

- **Worker** (`worker/`): `python -m worker.main --once` in a GitHub Action; the Action
  restores the Laya checkpoint from a GitHub release and fails (emailing the owner) if no
  event landed for 3 hours.
- **API** (`server/`): FastAPI, REST and WebSocket, migrations on start.
- **Web** (`web/`): Vite SPA with globe.gl; landing at `/`, dashboard at `/app/`.
- **Engine** (`finscrape/`): scrapers, LLM analysis, sector chain, scenarios, backtest.
- **LLM**: any OpenAI-compatible endpoint. Production runs `deepseek-v4.1-flash:free` with
  `mimo-v2.6-flash:free` as fallback; `make llm MODEL=... URL=... KEY=...` switches it
  everywhere.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · deploy and operations:
[docs/DEPLOY.md](docs/DEPLOY.md), [docs/RUNBOOK.md](docs/RUNBOOK.md).

---

## 🔧 Configuration

All via env (`.env.example`). Key ones:

| Var | Purpose |
|-----|---------|
| `WORLDFIN_DATABASE_URL` | Postgres DSN |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `FINSCRAPE_MODEL` | LLM endpoint, key and model |
| `FINSCRAPE_MODEL_FALLBACK` | Second model tried when the first fails |
| `FINSCRAPE_HEURISTIC_FALLBACK` | Ingest with keyword analysis when every model fails |
| `FINSCRAPE_LAYA`, `FINSCRAPE_LAYA_MODEL` | Laya sector classifier on/off and checkpoint path |
| `RELIEFWEB_APPNAME` | Approved ReliefWeb app name; the source is off without it |
| `WORLDFIN_ENABLE_COUNCIL` | Council endpoint |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Telegram alerts and bot commands |

---

## 🧪 Testing

```bash
make ci          # ruff, format, pyright, selfcheck, pytest, web typecheck/test/build, Playwright
make test        # pytest; DB tests need WORLDFIN_TEST_DATABASE_URL naming a *_test database
make e2e-live    # the built SPA against the real API and a seeded, empty *_test database
```

About 1,190 pytest cases, 69 vitest cases and 6 Playwright specs; CI runs all of them.

---

## 📂 Layout

```
finscrape/     engine: scrapers/world, ingestors, analysis (LLM, Laya, tickers), scenarios, council
server/        FastAPI app, routes, migrations, seed
worker/        ingest cycle, sources, correlation, backtest
web/           Vite SPA (landing + dashboard)
scripts/       llm.py (switch LLM), check_prod.py, db_backup.py, laya_train/ (fine-tuning)
ops/ingest-cron/  Cloudflare cron Worker that dispatches ingest and keeps the API warm
docs/          architecture, deploy, runbook, data sources, demo, security
```

`dashboard/` and [SETUP_WINDOWS.md](SETUP_WINDOWS.md) belong to the older standalone app.
Current work is in [task.md](task.md); what is known and measured is in [notes.md](notes.md).

---

## 📄 License

[MIT](LICENSE) — WorldFin is market intelligence, **not financial advice**.

Built on [globe.gl](https://github.com/vasturiano/globe.gl), [FastAPI](https://fastapi.tiangolo.com),
[spaCy](https://spacy.io), [Laya](https://pypi.org/project/laya/), [Supabase](https://supabase.com)
and [Cloudflare Pages](https://pages.cloudflare.com).
