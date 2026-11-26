# FinScrape — cost and free-tier limits

The live stack costs **$0/month** on four free services and a free LLM. This page states
the ceiling of each one, which ceiling is hit first, and what the first paid step costs.
Prices were read from the vendors' own pricing pages on **2026-11-24**; anything the repo
can measure is marked `verified-here`, anything that needs a production reading is marked
`needs-verify`.

`docs/DEPLOY.md` covers how each layer is wired; this page is only the money.

## What is free, and what ends it

| Layer | Service | Free ceiling | What ends it | First paid step |
|---|---|---|---|---|
| Web (landing + SPA) | Cloudflare Pages `winfin` | static hosting on the free plan, no sleep (`docs/DEPLOY.md`) | the free plan's build quota, far above one deploy per push (`needs-verify` against the account) | Pages paid plan — not needed at current volume |
| API | Render free web service `winfin-api` | 750 instance-hours/month, 512 MB RAM, 5 GB bandwidth; **spins down after 15 min without traffic**, ~1 min cold start | daily ingest mode: cron pings stop, first request pays the cold start (`docs/DEPLOY.md`, 30–50 s measured there — `needs-verify` after the last deploy) | Starter **$7/month**, 0.5 CPU / 512 MB, never sleeps |
| Database | Supabase Free, Seoul | **500 MB database**, 2 active projects; **pauses after 7 days of low activity** | the event table grows past 500 MB — the worker evicts down to `WORLDFIN_DB_MAX_MB` (**400 MB**, `server/settings.py`) and `scripts/check_prod.py` fails the run above 450 MB | Pro **from $25/month**, 8 GB disk, no pausing |
| Worker | GitHub Actions `ingest.yml` | free on a public repository: GitHub-hosted runner minutes are not metered | not close: one daily run is minutes | — none needed |
| Scheduler | Cloudflare cron Worker `winfin-ingest-cron` | Workers free plan request quota — `needs-verify` against the account; the schedule needs 48 dispatches/day at :13 and :43 (`docs/DEPLOY.md`) | the daily request quota, currently orders of magnitude above 48 | Workers paid plan $5/month — not needed |
| LLM | TokenHarbor free models (`deepseek-v4.1-flash:free`, fallback `mimo-v2.6-flash:free`) | usage caps per account; the exact quota is not published — `needs-verify` against the account dashboard | a `429`/`request_forbidden` reply; the key queue rotates, then the heuristic fallback answers so ingest never stalls | a paid OpenAI-compatible endpoint; see "Per-event and per-read cost" below for the measured figure |

## What breaks first

In order, with the knob that moves it:

1. **Database size.** 500 MB is the smallest hard wall and the only one that loses data if
   it is crossed (`event_retention_days=365`, eviction to `db_max_mb=400`). A month of daily
   ingest at the default `worker_max_articles=20` is far below it — the actual MB per event
   is `needs-verify` (no production reading in this repo; the daily `check_prod.py` alert
   reports it).
2. **LLM quota.** Free-model caps are the ceiling a busy day reaches next. The failure is
   already absorbed: the event is stored with a heuristic verdict instead of a model one
   (M1.3 makes that visible per row).
3. **Cold starts.** Daily mode means the API sleeps between ingests, so the first caller
   waits. This is a latency cost, not a money cost, until the Starter plan is bought.
4. **Render bandwidth (5 GB) and build minutes (500/month)** are an order of magnitude away —
   both are Render Hobby-plan figures read on 2026-11-24.

## What the paid step costs, in order of value

| Buy | Price | Buys |
|---|---|---|
| Render Starter | $7/month | no cold start, always-on API — the first thing a real user notices |
| Supabase Pro | $25/month | 8 GB disk and no pause-on-inactivity — buys ~16× the event headroom |
| Workers Paid | $5/month | only if the cron schedule tightens past the free request quota |

Total to remove every user-visible limit: **$32/month** (Render $7 + Supabase $25). The
LLM stays free until the free models are the bottleneck; the fallback is a heuristic
verdict, not an outage.

## Per-event and per-read cost

Measured in this repo on **2026-11-26**. Token counts are a **4 chars/token estimate, not a
tokenizer count**. Every number below is derived from a char count or a byte count plus the
published price list; no provider invoice was involved.

### One analysed event (LLM)

Inputs: the `v1` prompts from `finscrape/analysis/prompt_registry.py`, rendered over the
`_article()` fixture in `tests/test_analysis_cost.py`, and its `_reply()` dict serialised
with `json.dumps`.

| Part | Chars (measured) | Tokens (4 chars/token estimate, not a tokenizer count) |
|---|---|---|
| System prompt | 2,445 | 612 |
| User prompt (template plus fenced article) | 5,841 | 1,461 |
| Prompt total | 8,286 | 2,073 |
| Completion (reply JSON) | 355 | 89 |
| Event total | 8,641 | 2,162 |

Prompt tokens are the sum of the two rounded parts (612 + 1,461 = 2,073); the event total is
2,073 + 89 = 2,162. Prices for OpenRouter model `deepseek/deepseek-v4.1-flash-1017`:
**$0.00000015** per prompt token ($0.15/M) and **$0.0000006** per completion token ($0.60/M),
read from `https://openrouter.ai/api/v1/models` on **2026-11-26**.

| Line | Arithmetic (derived) | Cost |
|---|---|---|
| Prompt | 2,073 x 0.00000015 | $0.000310950 |
| Completion | 89 x 0.0000006 | $0.000053400 |
| Per event | 0.000310950 + 0.000053400 | $0.000364350 |
| Per 1,000 events | 0.000364350 x 1000 | $0.364350 |
| Per 10,000 events | 0.000364350 x 10000 | $3.643500 |

The configured production rows are the `:free` variants of these ids, so the live LLM cost is
**$0** today. This paid table is the first paid step for the LLM tier: it replaces the
heuristic fallback only once the free quota is the bottleneck.

### Per 10,000 API reads

| Measure | Value (derived) |
|---|---|
| Request | `GET /api/events?limit=50` with `Accept-Encoding: identity` |
| Port | 18080 (first free port from 18080) |
| Events returned by the local test database | 2 |
| Body bytes for that page (2 events) | 1,244 |
| Content-Length | 1,244, equal to the body, so no compression |
| Bytes per event | 622 (1,244 / 2) |
| 50-event page, scaled | 31,100 bytes (622 x 50) |
| Per 10,000 reads | 311,000,000 bytes = 296.59 MB (31100 x 10000 / 1024 / 1024) |
| Reads to fill Render's 5 GB | 172,627 (5 x 1024^3 / 31,100, rounded) |

The page held 2 rows, not 50, so the byte figure is the observed 622 bytes per event scaled
to a full 50-event page. Reads are not billed per request on any plan in use, so this is a
bandwidth number, not a price; a browser also receives gzip, so the identity response here is
an upper bound. The first paid steps stay: Render Starter **$7/month**, Supabase Pro
**$25/month**, and the per-token LLM cost above.

### First paid step per tier

| Tier | Free today | First paid step | What it changes |
|---|---|---|---|
| LLM | TokenHarbor free models | a paid OpenAI-compatible endpoint | $0.364350 per 1,000 events at the prices above; no quota fallback |
| API | Render free, sleeps after 15 min | Render Starter, $7/month | removes the cold start; 10,000 reads use 296.59 MB of the 5 GB |
| Database | Supabase Free, 500 MB | Supabase Pro, from $25/month | 8 GB disk, no 7-day pause; flat, not per event |
| Scheduler | Cloudflare Workers free | Workers Paid, $5/month | only if dispatch exceeds the free request quota; 48/day today |
| Web | Cloudflare Pages free | Pages paid plan | not needed at current build volume |

The free stack is $0/month. The first user-visible upgrade is Render Starter ($7); the first
cost that scales with volume is the LLM, at **$0.364350 per 1,000 analysed events**; the
database is the first hard ceiling.

### How to reproduce (2026-11-26)

Both probes are throwaway scripts outside the repo; no test was added.

1. Token and char counts, from the repo root:

   `PYTHONPATH=. .venv/Scripts/python.exe C:/Users/Yash/AppData/Local/Temp/opencode/m631_probe.py`

   The script imports `get_prompts("v1")` and `render_prompt`, builds the fixture article
   and the reply dict above, and prints `len()` for each part.

2. Served bytes: boot the API on a free port, wait for `/health` to return 200, then fetch
   one page and stop the server before the command exits:

   `WORLDFIN_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5433/worldfin_test WORLDFIN_RATE_LIMIT_PER_MIN=0 WORLDFIN_WARM_SCENARIOS=0 .venv/Scripts/python.exe -m uvicorn server.main:app --port 18080`

   `curl -s -H 'Accept-Encoding: identity' -o page.json -w '%{size_download}\n' 'http://127.0.0.1:18080/api/events?limit=50'`

   `wc -c page.json` then `len(json.load(open("page.json"))["events"])`. The measured run
   used `httpx` with the same header and read `len(response.content)` plus `Content-Length`.

## Budget guard

`finscrape/analysis/budget.py` caps model spend per UTC day before the invoice
does. Every ingest calls it in-process, so it needs no workflow step and no second
script. Documented 2026-11-26.

| Variable | Default | Meaning |
|---|---|---|
| `FINSCRAPE_DAILY_TOKEN_CEILING` | `0` (off) | tokens allowed per UTC day; a non-zero value turns the guard on |
| `FINSCRAPE_BUDGET_STATE` | `tempfile.gettempdir()/finscrape-budget.json` | ledger file |
| `FINSCRAPE_OUTPUT_TOKEN_RESERVE` | `300` | tokens held back per attempt for the reply |

The ledger is one JSON object, `{"date": "YYYY-MM-DD", "tokens": N}`, rewritten
atomically after each reservation. A new UTC day starts from zero: the count is
not carried over and no history is kept, so the per-event `fallback_reason` in
`key_metrics` is the only record of why a row was downgraded.

When the day's allowance is spent, `call_ai` returns `None` and the article is
analysed by the deterministic heuristic instead of the model, even with
`FINSCRAPE_HEURISTIC_FALLBACK` unset. Ingest keeps running. The stored event
carries `analysis_source == "heuristic"` and
`key_metrics["fallback_reason"] == "daily_token_ceiling"`, so a downgraded
verdict is visible rather than silent.

Read the current state from the repo root:

```bash
.venv/Scripts/python.exe -c "from finscrape.analysis import budget; print(budget.status())"
```

Honest limits: the state file is per host. The API and the worker do not share it,
and GitHub Actions starts from a fresh temporary directory each run unless
`FINSCRAPE_BUDGET_STATE` points at a persisted path. A single global ceiling needs a
shared counter such as Redis, the same stage as the shared rate limiter; this guard
is a ceiling per process host, not a fleet-wide one.

## Related

- `docs/DEPLOY.md` — the deploy itself and the "Known free-tier limits" that this page
  expands.
- `scripts/check_prod.py` — the alert that fires before the database ceiling
  (`MAX_MB = 450`, ingest-gap check).
- `server/settings.py` — `db_max_mb`, `event_retention_days`, `worker_max_articles`,
  `analyze_dispatch_per_hour`.
