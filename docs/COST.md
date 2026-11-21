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
| LLM | TokenHarbor free models (`deepseek-v4.1-flash:free`, fallback `mimo-v2.6-flash:free`) | usage caps per account; the exact quota is not published — `needs-verify` against the account dashboard | a `429`/`request_forbidden` reply; the key queue rotates, then the heuristic fallback answers so ingest never stalls | a paid OpenAI-compatible endpoint; cost per event is in M6.3 (`docs/COST.md` §"per-event" is `needs-verify` until then) |

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

- Tokens per analysed event, cost per 1,000 events, and cost per 10,000 API reads are
  **`needs-verify`** — they require a production database reading and a provider invoice,
  which no command in this repo produces. M6.3 adds the measurement; until then this page
  states ceilings only, never a per-event figure.

## Related

- `docs/DEPLOY.md` — the deploy itself and the "Known free-tier limits" that this page
  expands.
- `scripts/check_prod.py` — the alert that fires before the database ceiling
  (`MAX_MB = 450`, ingest-gap check).
- `server/settings.py` — `db_max_mb`, `event_retention_days`, `worker_max_articles`,
  `analyze_dispatch_per_hour`.
