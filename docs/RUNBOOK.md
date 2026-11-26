# FinScrape — Operations Runbook

How to operate, observe, restore, and rotate secrets for the FinScrape stack. Pairs with
[`SECURITY.md`](SECURITY.md) (threat model) and [`DATA_SOURCES.md`](DATA_SOURCES.md) (feeds).

## How to use this runbook

Read a step, run its command, then compare what you see against its Expected line. If the
observable does not match, run its Rollback line before trying anything else, and hand the
failure to the role named in its Escalate line as soon as that condition is met. Every
actionable step below states all three; a step without them is a doc bug.

## Escalation ladder

| Severity | Response window | Role | Use for |
|---|---|---|---|
| SEV1 | 15 min | Operator on call | production down, `/ready` 503, data loss |
| SEV2 | 1 hour | Repo owner | failed ingest or backup, stale sources, secret exposure |
| SEV3 | next business day | Repo owner | degraded metrics, drift, doc or workflow fixes |
| SEV4 | backlog | Repo owner | cosmetic issues, tuning ideas |

The operator on call owns first response, the repo owner owns the workflows plus Render and
Supabase settings, the database owner owns Postgres and backups, and the security owner owns
leaked credentials. Targets are in `docs/SLO.md`; the policy that spends them is in
`docs/ERROR-BUDGET.md`. Roles only here on purpose - paging handles live out of band.

## 0. Production (Pages + Render + Supabase + Actions)

### Production tasks

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

Expected: `gh run view --json status,conclusion` prints
`"status":"completed","conclusion":"success"` for the newest run, and `make llm ...` exits 0
after printing lines like `github variable MODEL set` and `render redeploy started`.
Rollback: re-run the same task with the previous value (`make llm MODEL=<old> URL=<old>
KEY=<old> FALLBACK=<old>`); undo a bad SPA deploy by redeploying the previous commit with the
same `cd web && ...` command.
Escalate: two consecutive non-zero exits, or a Render deploy still failing after 15 min ->
repo owner (SEV2).

### Alerts

**Alerts.** A failed ingest run emails the owner. The last step, `scripts/check_prod.py`, fails
the run when no event landed for 3 hours or the database passes 400 MB (the free cap is 500 MB).
Usual causes of "no event": the cron Worker's `GH_TOKEN` expired (renew with
`npx wrangler secret put GH_TOKEN` in `ops/ingest-cron`), every model failing (switch with
`make llm`), or Supabase paused.

Expected: `python -m scripts.check_prod.py` prints `newest event 0.1h old, database 214 MB` and
exits 0; a failing run logs a `::error::` line and GitHub emails the owner.
Rollback: none - read-only; the check never writes.
Escalate: no event for 3 h after one manual `gh workflow run ingest.yml`, or the database above
400 MB -> repo owner (SEV2) with `gh run view --log-failed` attached.

### Secrets in production

**Secrets in production** live in GitHub secrets (`WORLDFIN_DATABASE_URL`, `OPENAI_API_KEY`,
`BACKUP_KEY`), Render env, and the Worker secret `GH_TOKEN`; the LLM model, endpoint, fallback,
`LAYA_RELEASE` and `RELIEFWEB_APPNAME` are GitHub repo variables.

Expected: `gh secret list` and `gh variable list` show the names above, and the next workflow run
reports `"status":"completed","conclusion":"success"` in `gh run view --json status,conclusion`.
Rollback: re-set the previous value (`gh secret set NAME`, value from the password manager) and
re-run the workflow.
Escalate: a leaked or unrecoverable secret -> security owner (SEV2); rotate before anything else.

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

Expected: `docker compose ps` shows `postgres` healthy and `api` running, and
`curl -s -o /dev/null -w '%{http_code}' localhost:8010/health` prints `200`.
Rollback: `docker compose down` stops the stack and keeps the `pgdata18` volume; never remove
that volume unless the data is a scratch copy.
Escalate: a container restarting twice after `docker compose up -d` -> operator on call (SEV1).

### Observability overlay
```bash
docker compose -f docker-compose.yml -f docker-compose.obs.yml up -d
# Grafana http://localhost:3000 (admin/admin) → "FinScrape — Observability" dashboard
# Prometheus :9090 · Loki :3100
```

Expected: Grafana answers `200` on `localhost:3000`, Prometheus on `:9090`, Loki `/ready` on
`:3100`, and the observability dashboard loads with series.
Rollback: `docker compose -f docker-compose.yml -f docker-compose.obs.yml down`, then
`docker compose up -d`; overlay configs in `obs/` are stateless.
Escalate: a missing datasource after both files are applied -> operator on call (SEV3).

### Health probes
- `GET /health` — liveness, always 200 (`degraded` if DB unreachable).
- `GET /ready` — readiness, 503 until the DB pool answers (orchestrator gate).
- `GET /api/health` — per-source freshness (OK/STALE/WARN/EMPTY).
- `GET /metrics` — Prometheus exposition (API). Worker metrics on `worker:9100/metrics`.

Expected: `/health` returns `200` with `"status":"ok"`; `/ready` returns `{"ready":true}` within
30 s of a start; `/api/health` lists each source; `/metrics` returns lines starting `# HELP`.
Rollback: none - read-only probes.
Escalate: `/health` 200 while `/ready` stays 503 for 5 min -> operator on call (SEV1);
`/api/health` EMPTY for every source -> repo owner (SEV2).

### Cold start and keep-warm

The free tier sleeps, and DEPLOY.md quotes a 30–50 s cold start. Measure it instead of
remembering it:

```bash
python -m scripts.warm --spawn                   # the process cost, locally (~3 s)
python -m scripts.warm --base-url "$API_URL"     # the hosted cost, including the sleep
```

The hosted number exits non-zero once it is worse than the 50 s DEPLOY.md quotes, because a
number that drifts is a number that stopped being true. `.github/workflows/warm.yml` is the
keep-warm step: the cron Worker dispatches it just before the ingest cycle, which is already
a scheduled wake-up. Set the `API_URL` repository variable for it; nothing in the repo
carries a `schedule:` block, so the Worker stays the only scheduler.

Expected: `python -m scripts.warm --base-url "$API_URL"` prints
`cold start: 34.2 s, within the 50 s quoted in docs/DEPLOY.md` and exits 0.
Rollback: none - read-only; it wakes the deployment and changes no state.
Escalate: exit 1 with a hosted number above 50 s -> repo owner (SEV3) to confirm the keep-warm
dispatch, not to raise the quoted number.

### Scaling notes
- Rate limiting + tiered cache are **in-process** (single API replica by design). Going
  multi-replica needs Redis — `WORLDFIN_REDIS_URL` is the documented seam (`server/cache.py`,
  `server/rate_limit.py`, `server/ws.py`).
- WS fan-out is in-process too; same Redis seam.
- The four stages and the measured trigger that earns each one are in
  [docs/SCALING.md](SCALING.md).

Expected: a single replica serves the load test, and `worldfin_ws_clients` drops to 0 after the
only API process restarts - proof the counter and fan-out are per process.
Rollback: none - read-only until Redis exists; undo a compose edit with `docker compose up -d`.
Escalate: sustained 429s or WS disconnects at one replica -> repo owner (SEV3) to check the
trigger measured in [docs/SCALING.md](SCALING.md).

---

## 2. Observe

### Signals and logs

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

Expected: `rate(worldfin_events_ingested_total[5m])` is non-zero after one ingest, and a request
log line carries the same `correlation_id` as its `X-Request-ID` header.
Rollback: none - read-only queries.
Escalate: a metric absent for 15 min while the stack is up -> operator on call (SEV2); no log
lines in Loki while `docker compose logs api` is busy -> operator on call (SEV3).

---

## 3. Common incidents

### A source shows STALE

Symptom: `/api/health` shows a source **STALE**. Likely cause: feed down or network. Action:
check `docker compose logs worker`; transient feeds self-heal next cycle. Persistent -> verify
the URL in `DATA_SOURCES.md`.

Expected: the next worker cycle logs a fresh fetch for the source and `/api/health` flips it
back to OK.
Rollback: none - read-only.
Escalate: still STALE after two cycles, or the feed URL returns 404 -> repo owner (SEV2) to fix
[DATA_SOURCES.md](DATA_SOURCES.md).

### A source shows WARN

Symptom: a source **WARN**. Likely cause: the producer threw. Action: the worker degrades that
source and keeps going; the last error is in `source_health.last_error`.

Expected: `select source, last_error from source_health` shows the newest traceback while the
cycle completes and the other sources stay OK.
Rollback: none - read-only; the worker degrades only that source.
Escalate: the same source WARN on three consecutive cycles -> repo owner (SEV2).

### `/ready` returns 503

Symptom: `/ready` returns 503. Likely cause: the DB pool cannot answer. Action: check
`postgres` health; `docker compose restart api` after the DB is back.

Expected: `docker compose ps postgres` shows healthy, then `/ready` returns
`{"ready":true}` with `200`.
Rollback: if `docker compose restart api` makes it worse, `docker compose down` then
`docker compose up -d` (the `pgdata18` volume is kept).
Escalate: the pool still refusing 10 min after postgres is healthy -> database owner (SEV1).

### 429 responses

Symptom: 429s. Likely cause: the per-IP rate limit. Action: raise
`WORLDFIN_RATE_LIMIT_PER_MIN` or front with a CDN; 0 disables.

Expected: after the new value and `docker compose up -d api`, `make loadtest RPS=50 SECONDS=10`
finishes with no 429 in its status breakdown.
Rollback: unset the variable (default limit) and `docker compose up -d api`.
Escalate: 429s from one client at the default limit -> repo owner (SEV3) for an abuse or CDN
decision.

### LLM analysis is generic

Symptom: LLM analysis is generic. Likely cause: no LLM configured or the call failed. Action:
expected graceful fallback (`server/ai.py`); set `OPENAI_BASE_URL`/`OPENAI_API_KEY`.
`worldfin_llm_request_seconds{outcome="error"}` rising = backend issue.

Expected: that error series stays flat and the next analysis names company-specific facts.
Rollback: none - read-only; the heuristic fallback is intended. If a wrong key was set, restore
the previous one in `.env` and `docker compose up -d api worker`.
Escalate: the error series rising for 15 min with a valid key -> repo owner (SEV2).

---

## 4. Backup & restore (Postgres)

### Logical backup

Data lives in the `pgdata18` volume. Logical backup:
```bash
docker compose exec -T postgres pg_dump -U worldfin worldfin | gzip > backup-$(date +%F).sql.gz
```

Expected: the command exits 0, `ls -lh backup-$(date +%F).sql.gz` shows a non-empty file, and
`gunzip -t backup-$(date +%F).sql.gz` passes.
Rollback: none against the live DB; delete a partial archive with
`rm backup-$(date +%F).sql.gz` and retry.
Escalate: `pg_dump` exits non-zero twice -> database owner (SEV2).

### Restore into a fresh DB

Restore into a fresh DB:
```bash
gunzip -c backup-YYYY-MM-DD.sql.gz | docker compose exec -T postgres psql -U worldfin worldfin
```
Migrations are idempotent and run on startup (`WORLDFIN_RUN_MIGRATIONS=true`); a restored dump
already has the schema, so this is a no-op safety net. Events are content-deduped on ingest, so
re-running the worker after a restore won't double-insert.

Expected: `psql` exits 0 and `select count(*) from events` on the target equals the count in the
source dump.
Rollback: stop ingest, then restore the last good dump with
`make restore FILE=backups/worldfin-<utc>.dump`; only on a scratch target drop and recreate it
(`docker compose exec -T postgres dropdb -U worldfin worldfin`).
Escalate: a row count that differs -> database owner (SEV1); keep ingest stopped until it matches.

### Restore drill (run it, time it, write it down)

A backup nobody has restored is a hypothesis. The drill dumps (or decrypts) an archive,
verifies `pg_restore --list` can read it, restores into `<source>_drill`, compares row
counts against the source, runs the API's own `/api/stats` aggregate against the restored
copy, then drops the scratch database:

```bash
# against the test database (default; it refuses a DSN that is not *_test)
WORLDFIN_TEST_DATABASE_URL=postgresql://.../_test make restore-drill

# from the newest encrypted production backup
BACKUP_KEY=... python -m scripts.restore_drill --dump backups/worldfin-<stamp>.dump.enc --record
```

`--record` appends one row below. The number to watch is not the seconds — it is the row
counts: a restore that comes back one table short is the failure that matters.

| run (UTC) | source | archive | restore time | app check | rows verified |
|---|---|---|---|---|---|
| 2026-11-24T18:06:59Z | worldfin_test | 90 objects | 1.8 s | /api/stats total_events=1 | events 1, accuracy_outcomes 0, correlations 3, source_health 2 |

Expected: `make restore-drill` exits 0, prints the restore time plus `rows verified`, and
`--record` appends exactly one row to the table above.
Rollback: `docker compose exec -T postgres dropdb -U worldfin <source>_drill` if the script
aborted before its own cleanup.
Escalate: a table short or an `/api/stats` mismatch -> database owner (SEV2); a missing
`BACKUP_KEY` for the encrypted archive -> repo owner (SEV2).

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

Expected: `docker compose exec postgres psql -U worldfin -c 'select version()'` reports 18.x,
`/ready` returns `200`, and `make restore` printed the dump it consumed.
Rollback: `docker compose down`, re-point compose at `postgres:16` with the old `pgdata` volume,
and `docker compose up -d` - the old volume is still there because it is dropped last.
Escalate: `make restore` fails twice, or the row counts differ -> database owner (SEV1); do not
drop `pgdata` until the 18 stack has served a successful drill.

---

## 5. Secret rotation

### Rotating a secret

All secrets come from `.env` / the environment — no secrets in the image or git.

| Secret | Var | Rotate |
|---|---|---|
| Ingest API key | `FINSCRAPE_API_KEY` | set new value, `docker compose up -d api worker`; update any caller. |
| LLM key | `OPENAI_API_KEY` | set new in `.env`, recreate `api`+`worker`; in production `make llm KEY=...`. |
| DB password | `POSTGRES_PASSWORD` + DSN in `WORLDFIN_DATABASE_URL` | `ALTER USER worldfin PASSWORD '…';` then update both vars and recreate `api`+`worker`. |
| Grafana admin | `GRAFANA_PASSWORD` | set and recreate `grafana`. |

After rotation, confirm green: `/health`, `/ready`, and one authenticated mutating route.

Expected: `/health` returns `200`, `/ready` returns `{"ready":true}`, and one authenticated
mutating route (for example a `POST` with `X-API-Key: $FINSCRAPE_API_KEY`) returns 2xx.
Rollback: put the previous value back in `.env` and `docker compose up -d api worker`; in
production `make llm KEY=<previous>`.
Escalate: 401/403 on every caller after rotation -> security owner (SEV2); DB auth failures
-> database owner (SEV1).

---

## 6. Log retention

### Retention settings

Container stdout/stderr → Docker json-file driver (cap with `--log-opt max-size`/`max-file` or a
daemon-level default). Loki retention is set in `obs/loki-config.yml`; Prometheus TSDB retention
is `--storage.tsdb.retention.time` in `docker-compose.obs.yml` (15d default). Tune both to disk.

Expected: `docker inspect --format '{{.HostConfig.LogConfig}}' <container>` shows the json-file
cap, and Loki answers `200` on `:3100/ready` with the retention from `obs/loki-config.yml`.
Rollback: remove the `--log-opt` or retention override and recreate the container; lines already
deleted are gone, so lower the cap before, not after, a full disk.
Escalate: the disk above 80% despite the caps -> operator on call (SEV2).

## 7. Database retention

Each ingest cycle ends with a retention sweep. `WORLDFIN_RETENTION_DAYS` (default 90) ages out
correlations, scrape runs, the LLM cache, visited URLs and alert history. `WORLDFIN_EVENT_RETENTION_DAYS`
(default 365) deletes events older than that together with their scored outcomes, so the free
database cannot fill up and the accuracy record is a rolling year. Set either to 0 to keep forever.
Above `WORLDFIN_DB_MAX_MB` (default 400) the sweep also drops the oldest events in 5% batches and compacts, so ingest never stops on a full database. `scripts/check_prod.py` fails the run only above 450 MB, which means eviction failed.
