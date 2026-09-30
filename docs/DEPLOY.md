# WorldFin — free-tier production deploy

The live stack runs **$0/month, no credit card** across four free services + a free LLM.

## Live URLs
- **Landing:** https://winfin.pages.dev
- **Dashboard:** https://winfin.pages.dev/app/
- **API:** https://winfin-api.onrender.com (`/docs`, `/health`)

## Architecture
| Layer | Service | Notes |
|---|---|---|
| Web (landing + SPA) | **Cloudflare Pages** (`winfin`) | static, no sleep; landing `/`, app `/app/` |
| API | **Render** free web service (`winfin-api`, Singapore) | Docker `Dockerfile.api` → Supabase; kept warm by a 10-minute ping |
| Database | **Supabase** Postgres (Seoul, `bfzkjwucytbtnmzomtvt`) | session pooler, port 5432; RLS on every table so the Data API exposes nothing |
| Worker | **GitHub Actions** (`.github/workflows/ingest.yml`), dispatched at :13/:43 by the Cloudflare cron Worker `winfin-ingest-cron` (`ops/ingest-cron`) | `python -m worker.main --once`; GitHub's own schedule stays as a fallback but fires only every 3–6 hours |
| LLM | **TokenHarbor** free models, primary + fallback (`FINSCRAPE_MODEL_FALLBACK`) | Primary `deepseek-v4.1-flash:free`, fallback `mimo-v2.6-flash:free` (owner's choice, 30 Sep). OpenAI chat API at `https://tokenharbor.ai/v1`. Heuristic fallback covers a full outage |

## Environment

**Render API** (`srv-...` env vars) and **GitHub Actions secrets** share:
- `WORLDFIN_DATABASE_URL` — Supabase session pooler: `postgresql://postgres.<project>:<password>@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres`
- `OPENAI_BASE_URL=https://tokenharbor.ai/v1`, `OPENAI_API_KEY=<TokenHarbor key>`, `FINSCRAPE_WIRE_API=chat`, `FINSCRAPE_MODEL=mimo-v2.6-flash:free`
- `FINSCRAPE_HEURISTIC_FALLBACK=true` (worker — ingest never stalls if the LLM is down)

API-only: `WORLDFIN_ENV=production` (refuses the default key and CORS `*`), `WORLDFIN_CORS_ORIGINS=https://winfin.pages.dev`, `FINSCRAPE_API_KEY`, `WORLDFIN_RUN_MIGRATIONS=true`, `WORLDFIN_ENABLE_COUNCIL=true`, `FINSCRAPE_LAYA=0` (the image carries no Laya).

Ingest Action only: the repo variable `LAYA_RELEASE` names the GitHub release holding the Laya checkpoint (`laya.tar`); the job installs CPU-only torch, caches the checkpoint per tag and sets `FINSCRAPE_LAYA_MODEL`. Publish a new checkpoint with `python scripts/laya_train/publish.py` (the daily Laya job does this on promotion); unset the variable to run without Laya.

The API reads `$PORT` (Render injects it; `settings.port` aliases `WORLDFIN_PORT`/`PORT`).

## Redeploy
- **Web:** `cd web && VITE_API_BASE=https://winfin-api.onrender.com npm run build && npx wrangler pages deploy dist --project-name=winfin --branch=main`
- **API:** push to `master` → Render auto-deploys (`autoDeploy: yes`). Or POST a deploy via the Render API.
- **Worker:** runs every 30 min automatically; `gh workflow run ingest.yml` to fire now.
- **Ingest cron:** `cd ops/ingest-cron && npx wrangler deploy`; its `GH_TOKEN` secret is a fine-grained PAT (this repo, Actions read and write), set with `npx wrangler secret put GH_TOKEN`.

## Keep-warm, alerts, backups
- The cron Worker also pings `/health` every 10 minutes, so Render never sleeps.
- Each ingest run ends with `scripts/check_prod.py`: it fails the run (GitHub emails the owner) when no event landed for 3 hours or the database passes 400 MB.
- `backup.yml` dumps production nightly, encrypted with `BACKUP_KEY` (GitHub secret and local `.env`), as a 14-day artifact. Restore: `gh run download <run> -n worldfin-<run>`, then `openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_KEY -in worldfin.dump.enc -out worldfin.dump` and `pg_restore -d <url> --no-owner worldfin.dump`.

## Known free-tier limits
- Worker updates the dashboard on **refresh**, not live WS push (cross-process WS needs Redis — deferred).
- GitHub cron can be delayed/skipped under load (~"every 30 min", not exact).
- Supabase free: 500 MB database, paused after a week without activity (the ingest cron keeps it active); TokenHarbor free models have usage caps — the heuristic fallback absorbs LLM exhaustion.

## Choosing the model
Measured 29 Sep 2026 on the 56-headline sector gold set with the real analysis prompt:

| Model | Valid JSON | Sector accuracy | p50 latency |
|---|---|---|---|
| `qwen3.8-flash:free` | 79% | 79.5% | 30 s (p90 82 s) |
| `mimo-v2.6-flash:free` | 96% | 66.7% | 14 s (p90 21 s) |
| `deepseek-v4.1-flash:free` | 77% | 67.4% | 13 s (p90 32 s) |

## Keys / secrets
These are **temporary throwaway account keys** — kept in **GitHub → Settings → Secrets** and
**Render → Environment** only (never in the repo, never in the database).

To switch model, endpoint or key, run one command (any subset of the four):

    make llm MODEL=deepseek-v4.1-flash:free URL=https://tokenharbor.ai/v1 KEY=sk-... FALLBACK=mimo-v2.6-flash:free

It sets the GitHub variables (`FINSCRAPE_MODEL`, `OPENAI_BASE_URL`, `FINSCRAPE_MODEL_FALLBACK`)
and the `OPENAI_API_KEY` secret that the ingest and reanalyse Actions read, then the same
env vars on the Render API and redeploys it. Render needs `RENDER_API_KEY` in `.env`;
without it the command prints the values to paste into the Render dashboard.
