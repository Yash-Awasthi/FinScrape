# FinScrape — Operations Runbook

How to operate, observe, restore, and rotate secrets for the FinScrape stack. Pairs with
[`SECURITY.md`](SECURITY.md) (threat model) and [`DATA_SOURCES.md`](DATA_SOURCES.md) (feeds).

## 0. Production (Pages + Render + Supabase + Actions)

| Task | Command |
|---|---|
| Switch LLM model, endpoint or key | `make llm MODEL=... URL=... KEY=... FALLBACK=...` (Actions + Render; Render needs `RENDER_API_KEY` in `.env`) |
| Run ingest now | `gh workflow run ingest.yml` |
| Re-run the LLM over heuristic rows | `gh workflow run reanalyse.yml -f days=7` |
| Back up now | `gh workflow run backup.yml` (nightly anyway, 14 days kept) |
| Restore a backup | see "Keep-warm, alerts, backups" in [DEPLOY.md](DEPLOY.md) |
| Publish a Laya checkpoint | `python scripts/laya_train/publish.py` (the nightly job does it on promotion) |
| Redeploy the SPA | `cd web && VITE_API_BASE=https://winfin-api.onrender.com npm run build && npx wrangler pages deploy dist --project-name=winfin --branch=main` |
| Redeploy the API | merge to `master` (Render auto-deploys) |
| Redeploy the cron Worker | `cd ops/ingest-cron && npx wrangler deploy` |

**Alerts.** A failed ingest run emails the owner. The last step, `scripts/check_prod.py`, fails
the run when no event landed for 3 hours or the database passes 400 MB (the free cap is 500 MB).
Usual causes of "no event": the cron Worker's `GH_TOKEN` expired (renew with
`npx wrangler secret put GH_TOKEN` in `ops/ingest-cron`), every model failing (switch with
`make llm`), or Supabase paused.

**Secrets in production** live in GitHub secrets (`WORLDFIN_DATABASE_URL`, `OPENAI_API_KEY`,
`BACKUP_KEY`), Render env, and the Worker secret `GH_TOKEN`; the LLM model, endpoint, fallback,
`LAYA_RELEASE` and `RELIEFWEB_APPNAME` are GitHub repo variables.

---

The rest of this runbook covers the docker compose stack.

Stack = **postgres** + **api** (FastAPI :8010 on the host) + **worker** (APScheduler) + **web** (nginx :8080).
Optional observability overlay = **prometheus** + **grafana** + **loki** + **alloy** (log shipper).

---

## 1. Operate

### Bring up / tear down
```bash
cp .env.example .env            # set OPENAI_BASE_URL/OPENAI_API_KEY/FINSCRAPE_MODEL; else LLM falls back
docker compose up -d            # core stack
docker compose ps               # health
docker compose logs -f api      # tail one service
docker compose down             # stop (keeps the pgdata18 volume)
```

With observability:
```bash
docker compose -f docker-compose.yml -f docker-compose.obs.yml up -d
# Grafana http://localhost:3000 (admin/admin) → "FinScrape — Observability" dashboard
# Prometheus :9090 · Loki :3100
```

### Health probes
- `GET /health` — liveness, always 200 (`degraded` if DB unreachable).
- `GET /ready` — readiness, 503 until the DB pool answers (orchestrator gate).
- `GET /api/health` — per-source freshness (OK/STALE/WARN/EMPTY).
- `GET /metrics` — Prometheus exposition (API). Worker metrics on `worker:9100/metrics`.

### Scaling notes
- Rate limiting + tiered cache are **in-process** (single API replica by design). Going
  multi-replica needs Redis — `WORLDFIN_REDIS_URL` is the documented seam (`server/cache.py`,
  `server/rate_limit.py`, `server/ws.py`).
- WS fan-out is in-process too; same Redis seam.

---

## 2. Observe

| Signal | Where | Metric / query |
|---|---|---|
| Ingest rate | Grafana / Prom | `rate(worldfin_events_ingested_total[5m])` |
| Duplicates | Prom | `rate(worldfin_events_duplicate_total[5m])` |
| LLM latency p95 | Grafana / Prom | `histogram_quantile(0.95, rate(worldfin_llm_request_seconds_bucket[5m]))` |
| Source freshness | Grafana / Prom | `worldfin_source_age_seconds`, `worldfin_source_up` |
| WS clients | Prom | `worldfin_ws_clients` |
| HTTP rate/latency | Prom | `worldfin_http_requests_total`, `worldfin_http_request_seconds` |
| Logs | Loki/Grafana | `{container=~".*api.*|.*worker.*"}` |

Logs are one-line JSON when `WORLDFIN_LOG_JSON=true` (default in compose) with a
`correlation_id` per HTTP request (also returned in the `X-Request-ID` response header) and
per worker source-cycle — grep one id to trace a unit of work end to end.

---

## 3. Common incidents

| Symptom | Likely cause | Action |
|---|---|---|
| `/api/health` shows a source **STALE** | feed down / network | check `docker compose logs worker`; transient feeds self-heal next cycle. Persistent → verify the URL in `DATA_SOURCES.md`. |
| A source **WARN** | producer threw | the worker degrades that source and keeps going; last error is in `source_health.last_error`. |
| `/ready` returns 503 | DB pool can't answer | check `postgres` health; `docker compose restart api` after DB is back. |
| 429s | per-IP rate limit | raise `WORLDFIN_RATE_LIMIT_PER_MIN` or front with a CDN; 0 disables. |
| LLM analysis is generic | no LLM configured or call failed | expected graceful fallback (`server/ai.py`); set `OPENAI_BASE_URL`/`OPENAI_API_KEY`. `worldfin_llm_request_seconds{outcome="error"}` rising = backend issue. |

---

## 4. Backup & restore (Postgres)

Data lives in the `pgdata18` volume. Logical backup:
```bash
docker compose exec -T postgres pg_dump -U worldfin worldfin | gzip > backup-$(date +%F).sql.gz
```
Restore into a fresh DB:
```bash
gunzip -c backup-YYYY-MM-DD.sql.gz | docker compose exec -T postgres psql -U worldfin worldfin
```
Migrations are idempotent and run on startup (`WORLDFIN_RUN_MIGRATIONS=true`); a restored dump
already has the schema, so this is a no-op safety net. Events are content-deduped on ingest, so
re-running the worker after a restore won't double-insert.

### Upgrading Postgres (16 to 18)
Postgres 16 stored its data in the `pgdata` volume; 18 uses `pgdata18`, because a data
directory cannot cross major versions. Move it with a logical dump:
```bash
git checkout <commit before the upgrade>   # compose still on postgres:16 + pgdata
docker compose up -d postgres
make backup                                 # backups/worldfin-<utc>.dump
docker compose down
git checkout master
docker compose up -d postgres               # fresh 18 cluster in pgdata18
make restore FILE=backups/worldfin-<utc>.dump
docker compose up -d
```
Once the stack checks out, drop the old volume with `docker volume rm <project>_pgdata`.

---

## 5. Secret rotation

All secrets come from `.env` / the environment — no secrets in the image or git.

| Secret | Var | Rotate |
|---|---|---|
| Ingest API key | `FINSCRAPE_API_KEY` | set new value, `docker compose up -d api worker`; update any caller. |
| LLM key | `OPENAI_API_KEY` | set new in `.env`, recreate `api`+`worker`; in production `make llm KEY=...`. |
| DB password | `POSTGRES_PASSWORD` + DSN in `WORLDFIN_DATABASE_URL` | `ALTER USER worldfin PASSWORD '…';` then update both vars and recreate `api`+`worker`. |
| Grafana admin | `GRAFANA_PASSWORD` | set and recreate `grafana`. |

After rotation, confirm green: `/health`, `/ready`, and one authenticated mutating route.

---

## 6. Log retention

Container stdout/stderr → Docker json-file driver (cap with `--log-opt max-size`/`max-file` or a
daemon-level default). Loki retention is set in `obs/loki-config.yml`; Prometheus TSDB retention
is `--storage.tsdb.retention.time` in `docker-compose.obs.yml` (15d default). Tune both to disk.

## 7. Database retention

Each ingest cycle ends with a retention sweep. `WORLDFIN_RETENTION_DAYS` (default 90) ages out
correlations, scrape runs, the LLM cache, visited URLs and alert history. `WORLDFIN_EVENT_RETENTION_DAYS`
(default 365) deletes events older than that together with their scored outcomes, so the free
database cannot fill up and the accuracy record is a rolling year. Set either to 0 to keep forever.
Above `WORLDFIN_DB_MAX_MB` (default 400) the sweep also drops the oldest events in 5% batches and compacts, so ingest never stops on a full database. `scripts/check_prod.py` fails the run only above 450 MB, which means eviction failed.
