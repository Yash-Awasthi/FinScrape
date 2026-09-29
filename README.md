# 🌐 WorldFin — Free Geopolitical Market Intelligence

> **See what moves markets — before it's news.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13+-3776AB.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/Tests-737+-brightgreen.svg)](#testing)
[![Cost](https://img.shields.io/badge/Cost-$0%2Fmonth-brightgreen.svg)](#deploy-it-free)
[![Live](https://img.shields.io/badge/Live-Dashboard-blue.svg)](https://winfin.pages.dev/app/)

**WorldFin** is a free, open-source alternative to AlphaSense ($12k-$120k/year), MarketReader, and Reflexivity. It ingests geopolitics + world news, resolves **which tickers and sectors** each event moves, judges the **first- and second-order** market impact on a **live globe**, and **proves the calls were right** over time.

---

## 🆚 Why WorldFin?

| | WorldFin | AlphaSense | MarketReader | Reflexivity |
|---|---|---|---|---|
| **Price** | **$0/month** | $12k-$120k/year | Enterprise | Enterprise |
| **Open Source** | ✅ MIT | ❌ | ❌ | ❌ |
| **Live Globe** | ✅ | ❌ | ❌ | ❌ |
| **Accuracy Backtesting** | ✅ Hit-rate + equity curve | ❌ | ❌ | ❌ |
| **Multi-Agent Council** | ✅ 7 agents + judge | ❌ | ❌ | ❌ |
| **Geopolitical Focus** | ✅ Primary | Secondary | Secondary | Secondary |
| **Self-Hosted** | ✅ Docker | ❌ | ❌ | ❌ |
| **Free LLM** | ✅ Ollama / freemodel | ❌ | ❌ | ❌ |

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🌍 **Live Globe** | Every event geolocated, colored by verdict (INVEST / PULL_OUT / OBSERVE / CAUTIOUS) |
| 🎯 **Ticker Resolution** | Word-boundary matched company→ticker map + sector/region map for geopolitics |
| 🤖 **7-Agent Council** | Analyst personas debate with rebuttal rounds; judge model reads full transcript |
| 📊 **Accuracy Proof** | Backtested hit-rate, by-verdict breakdown, equity-curve sparkline, Brier score |
| 🔗 **Correlation Engine** | Fires when 3+ source-types corroborate; flags news↔market divergence |
| 💬 **Social Sentiment** | Bullish and bearish Reddit posts per ticker, read by RSS each ingest run |
| 📱 **Telegram Alerts** | Subscribe to INVEST/PULL_OUT signals via Telegram bot |
| 🔄 **Prompt A/B** | Test prompt variants with accuracy-by-variant comparison |
| 🏥 **Source Health** | Per-source freshness monitoring with circuit breakers |

---

## 🚀 Quick Start

Needs Docker and git. No LLM key is required: the demo loads a seeded dataset, and
the worker falls back to keyword analysis until a model is configured.

```bash
git clone https://github.com/Yash-Awasthi/fin-scrape.git && cd fin-scrape
cp .env.example .env
make demo                     # build, start postgres + api + worker + web, seed demo data
#   web → http://localhost:8080 (dashboard at /app/)   ·   api → http://localhost:8010/docs
```

Without `make`: `docker compose up -d --build`, then `docker compose exec api python -m server.seed`.
Stop with `make down` (`docker compose down`); add `-v` to drop the database.
Port taken? Set `WORLDFIN_API_HOST_PORT` (8010) or `WORLDFIN_PG_HOST_PORT` (5433) in `.env`;
the web port is 8080.

To analyse live news with a model, set `OPENAI_BASE_URL`, `OPENAI_API_KEY` and
`FINSCRAPE_MODEL` in `.env` (any OpenAI-compatible endpoint; a host Ollama is
`http://host.docker.internal:11434/v1` from inside compose) and run `docker compose up -d`.

### No Docker?

```bash
uv sync --group server                          # Python 3.13
# point WORLDFIN_DATABASE_URL in .env at a Postgres you run, then:
uv run python -m server.seed                    # optional demo data
uv run python -m server.main                    # API at :8010
uv run python -m worker.main --once             # one ingest cycle
cd web && npm ci && npm run dev                 # dashboard at :8080, proxies /api to :8010
```

See **[docs/DEMO.md](docs/DEMO.md)** for the scripted 5-minute walkthrough.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    GITHUB ACTIONS (Worker)                       │
│  scrape → LLM → resolve → ingest → correlate → backtest         │
├─────────────────────────────────────────────────────────────────┤
│                    DATA LAYER                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ 14 RSS Feeds│  │ 11 Stealth │  │ Keyless APIs│            │
│  │ (world +    │  │ Scrapers   │  │ (USGS/GDELT │            │
│  │  finance)   │  │ (Yahoo/    │  │ /ReliefWeb/ │            │
│  │             │  │  Reuters/  │  │ CoinGecko)  │            │
│  └──────┬──────┘  │  Bloomberg)│  └──────┬──────┘            │
│         │         └──────┬─────┘         │                     │
│         └────────────────┼───────────────┘                     │
│                          ▼                                      │
│              ┌──────────────────────┐                           │
│              │   finscrape Brain    │                           │
│              │  • LLM extraction   │                           │
│              │  • Entity resolution │                           │
│              │  • 7-agent council  │                           │
│              │  • Accuracy tracking │                           │
│              └──────────┬───────────┘                           │
├─────────────────────────┼───────────────────────────────────────┤
│                    NEON POSTGRES                                 │
│  events · correlations · accuracy · source_health · ai_cache    │
├─────────────────────────┼───────────────────────────────────────┤
│                    FASTAPI (Render)                              │
│  REST + WS + /docs · Ingest/Dedup · Correlation · Accuracy     │
├─────────────────────────┼───────────────────────────────────────┤
│                    VITE SPA (Cloudflare Pages)                  │
│  globe.gl · Panel Grid · Signal Feed · Accuracy Dashboard      │
└─────────────────────────┴───────────────────────────────────────┘
```

---

## 🤖 Multi-Agent Council

The council is WorldFin's explainability layer:

```
                    ┌─────────────────┐                     │   8 Analysts    │
                    │  (in parallel)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Round 1: Blind │
                    │  Independent    │
                    │  Scoring        │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Round 2+: Rebut│
                    │  See others'    │
                    │  reasoning      │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Judge Model    │
                    │  Reads full     │
                    │  transcript     │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Final Verdict  │
                    │  -5...+5 score  │
                    │  + rationale    │
                    └─────────────────┘
```

**Agents:** Analyst (1.5), Contrarian (1.0), Risk (1.2), Momentum (0.8), Fundamentals (1.0), Scout (0.7), Reviewer (1.4)

**Real numbers, not invented ones:** RSI14, SMA20/50, ATR%, 5-day return, % off 52-week high are computed and handed to every agent as ground truth. Conflicting numbers get flagged and discounted.

**Standalone package:** The council is also available as an independent library — [`pip install worldfin-council`](finscrape/council/README.md). Zero dependencies, bring your own LLM client via the `AiClient` protocol.

**Interactive demo:** See the council in action — [🌐 Open Council Dashboard](web/council.html) (mock data, runs in browser).

---

## 📊 Accuracy Backtesting

Every call is tracked against realized market moves:

```
Signal: INVEST XOM (+3.2)    →  XOM moved +4.1% in 5 days  ✅ Hit
Signal: PULL_OUT TSLA (-2.8) →  TSLA moved -1.2% in 5 days  ✅ Hit
Signal: OBSERVE AAPL (+0.5)  →  AAPL moved +3.8% in 5 days  ❌ Miss
```

**Metrics:** hit-rate, by-verdict breakdown, equity curve, Brier score, confidence calibration.

---

## 💰 Deploy Free ($0/month)

The entire stack runs on free tiers:

| Service | Provider | Cost |
|---------|----------|------|
| Web | Cloudflare Pages | $0 |
| API | Render (free tier) | $0 |
| Database | Neon Postgres | $0 |
| Worker | GitHub Actions | $0 |
| LLM | freemodel.dev / Ollama | $0 |

Full recipe in **[docs/DEPLOY.md](docs/DEPLOY.md)**.

---

## 🔧 Configuration

All via env (`.env.example`). Key ones:

| Var | Purpose |
|-----|---------|
| `WORLDFIN_DATABASE_URL` | Postgres DSN |
| `OPENAI_BASE_URL` + `OPENAI_API_KEY` | LLM backend (Ollama / freemodel) |
| `OPENROUTER_API_KEY` + `FINSCRAPE_MODEL` | BYOK LLM alternative |
| `FINSCRAPE_HEURISTIC_FALLBACK` | Ingest with heuristics when LLM unavailable |
| `WORLDFIN_ENABLE_COUNCIL` | Multi-agent explainability |
| `FINSCRAPE_COUNCIL_ROUNDS` | Council debate rounds (default: 1) |
| `TELEGRAM_BOT_TOKEN` | Outbound alerts |
| `TELEGRAM_WEBHOOK_SECRET` | Required for inbound bot commands; pass the same value to `setWebhook(secret_token=…)`. Unset means `/api/telegram/webhook` ignores every update. |

---

## 🧪 Testing

```bash
make test                      # pytest; DB tests need WORLDFIN_TEST_DATABASE_URL
# or
pytest tests/ -v               # Full suite
pytest tests/test_debate.py    # Council debate tests
pytest tests/test_accuracy.py  # Accuracy backtesting tests
```

**Coverage:** Council debate, judge model, accuracy calibration, ticker resolution, entity mapping, prompt injection defenses, correlation engine.

---

## 📈 Live Market Dashboard

Real-time market visualization with:
- Live price ticker with real-time updates
- Candlestick chart (CSS-only)
- Market sentiment gauge
- News feed with sentiment-colored borders
- Technical indicators (RSI, MACD, Bollinger, VWAP)
- 8-agent council consensus visualization
- Alert feed with triggered alerts
- Dark financial terminal aesthetic

**Open:** [dashboard.html](web/dashboard.html) (runs in browser, no server needed)

---

## 📂 Project Structure

```
fin-scrape/
├── finscrape/                 # Intelligence engine
│   ├── scrapers/world/        # 14 RSS feeds + keyless APIs
│   ├── analysis/              # LLM extraction, ticker resolution, NLP
│   ├── agents/                # 7-agent council + judge
│   ├── models/                # Pydantic data models
│   └── accuracy.py            # Hit-rate tracking
├── server/                    # FastAPI service
│   ├── routes/                # API endpoints
│   ├── ingest.py              # Content-hash dedup
│   ├── correlate.py           # Cross-source correlation
│   └── ws.py                  # WebSocket hub
├── worker/                    # APScheduler ingest worker
├── web/                       # Vite SPA (globe.gl + panels)
├── tests/                     # 737 tests
└── docs/                      # Architecture, deploy, demo, security
```

---

## 🗺️ Roadmap

- [ ] **Phase 14:** Options flow analysis + earnings call tone
- [ ] **Phase 15:** Custom financial NER fine-tuned on SEC filings
- [ ] **Phase 16:** Paper trading integration (Alpaca/IBKR)
- [ ] **Phase 17:** Discord/Slack alert channels
- [ ] **Phase 18:** Mobile app (React Native)

See **[PLAN.md](PLAN.md)** for the full 2-year roadmap.

---

## 🤝 Contributing

Contributions welcome! Open an issue or PR. See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the codebase layout.

---

## 📄 License

[MIT](LICENSE) — WorldFin is market intelligence, **not financial advice**.

---

## 🙏 Acknowledgments

Built on the shoulders of giants:
- [globe.gl](https://github.com/vasturiano/globe.gl) — 3D globe visualization
- [FastAPI](https://fastapi.tiangolo.com) — Modern Python web framework
- [spaCy](https://spacy.io) — Industrial-strength NLP
- [Ollama](https://ollama.ai) — Local LLM inference
- [Neon](https://neon.tech) — Serverless Postgres
- [Cloudflare Pages](https://pages.cloudflare.com) — Free static hosting
