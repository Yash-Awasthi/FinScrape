# FinScrape - Incident Playbooks

The six failures this service is known to produce. Each playbook names the observable
that identifies it, the operator response with its runbook link, a one-line revert, and
the evidence the repo owner needs. The escalation ladder, stack commands and rollback
templates live in [RUNBOOK.md](RUNBOOK.md); availability targets live in
[SLO.md](SLO.md). Every playbook has a matching local case in
`python -m scripts.incident_drill`.

## model-provider-outage

**Trigger:** the configured LLM backend refuses or is unreachable for every key, so
analysis falls back to keyword output instead of model-judged rows.

**Detection signal:**
- `GET /api/health` reports `heuristic_alert: true` with `heuristic_share_24h` above
  `0.20`, and `server/routes/health.py` logs the `heuristic_share_24h` warning that most
  recent events are not model-judged; the response reads `degraded` when the source
  rollup is also unhealthy.
- `worldfin_llm_request_seconds{outcome="error"}` keeps rising in Prometheus
  (see [RUNBOOK.md](RUNBOOK.md#2-observe)).
- `events` rows written with `analysis_source = 'heuristic'` instead of `model` or
  `model_repaired`.

**Response:**
1. Follow "LLM analysis is generic" in
   [RUNBOOK.md](RUNBOOK.md#3-common-incidents): read
   `worldfin_llm_request_seconds{outcome="error"}`, then the ingest log for
   `AI proxy error:` or `AI HTTP <status>:`.
2. Switch provider, model or key with the production table in
   [RUNBOOK.md](RUNBOOK.md#0-production-pages--render--supabase--actions):
   `make llm MODEL=... URL=... KEY=... FALLBACK=...`.
3. Re-judge the fallback rows with `gh workflow run reanalyse.yml -f days=7`.
4. Re-run the drill offline with `python -m scripts.incident_drill`; the
   `model_provider_outage` case drives `finscrape.analysis.ai_client` with the HTTP seam
   refusing and asserts the call returns `None` instead of raising.

**Rollback:** `make llm MODEL=<old> URL=<old> KEY=<old> FALLBACK=<old>` restores the
previous provider values.

**Escalation:** repo owner (single operator), SEV2, when two ingest runs still leave
`heuristic_alert: true`. Attach the failing GitHub run URL, the `X-Request-ID` /
`correlation_id` of one degraded `/api/health` request, and the verbatim
`AI proxy error:` or `AI HTTP <status>:` text.

## 429-exhaustion

**Trigger:** every key in the free queue has spent its allowance, so the provider answers
429 for each attempt and no model call can succeed.

**Detection signal:**
- Log line `AI proxy key ...<last4> answered 429, moved to the back` from
  `finscrape/analysis/ai_client.py`, once per spent key.
- Table `llm_key_queue` (`worker/key_queue.py`) has a recent `moved_at` for every key
  fingerprint; in-process, `ai_client.key_moves()` returns the same map.
- The `heuristic_share_24h` share from `GET /api/health` rises as the attempts fail.

**Response:**
1. Rotate or add keys with the procedure in
   [RUNBOOK.md](RUNBOOK.md#5-secret-rotation):
   `gh secret set OPENAI_API_KEYS --body "<key1,key2>"`.
2. Start one cycle with `gh workflow run ingest.yml`; expected: no
   `answered 429` line for the new key.
3. Re-judge stored rows with `gh workflow run reanalyse.yml -f days=7`.
4. Re-run the drill offline with `python -m scripts.incident_drill`; the
   `429_exhaustion` case replays the recorded 429 body for both keys and asserts every
   fingerprint lands in `ai_client.key_moves()` with `_call_openai_proxy` returning `None`.

**Rollback:** `gh secret set OPENAI_API_KEYS --body "<previous list>"` restores the
previous queue.

**Escalation:** repo owner (single operator), SEV3, for a quota decision; the caps are in
[COST.md](COST.md), and a paid endpoint is a separate change rather than more retries.
Attach the GitHub run URL, the provider 429 body text, the `llm_key_queue` rows
(`fingerprint`, `moved_at`), and the `X-Request-ID` of the `/api/health` call that showed
the rising heuristic share.

## supabase-paused

**Trigger:** the Supabase project is paused, so every database connect fails before any
query runs.

**Detection signal:**
- `GET /ready` returns `503` with `{"ready": false}` (`server/app.py`).
- `GET /api/health` returns `"status": "degraded"` with `"db": false` and an empty
  `sources` list (`server/routes/health.py`).
- `python -m scripts.check_prod.py` exits 1 and prints
  `::error::no new event for <n>h`.

Locally the drill simulates the observable symptom: an asyncpg connect to a closed port
is refused quickly, the same failure `/ready` maps to 503. It does not touch the real
Supabase project.

**Response:**
1. Follow "`/ready` returns 503" in [RUNBOOK.md](RUNBOOK.md#3-common-incidents): restore
   the paused project in the Supabase dashboard. That action is owner-only; no repo
   command can perform it.
2. After the project answers, run `gh workflow run ingest.yml`; expected:
   `GET /ready` returns `200` with `{"ready": true}` and
   `python -m scripts.check_prod.py` exits 0.
3. Re-run the drill offline with `python -m scripts.incident_drill`; the
   `supabase_paused` case asserts the connect raises `OSError` or `TimeoutError` within
   the 2 s bound.

**Rollback:** if a `WORLDFIN_DATABASE_URL` edit preceded the outage, restore the previous
Supabase session-pooler URL and redeploy the API; the restore itself changes no repo
state.

**Escalation:** repo owner (single operator), SEV1, until `/ready` answers 200. Attach the
`/ready` response body with its `X-Request-ID` / `correlation_id`, the verbatim
`ready: db check failed:` log text, the `::error::no new event for <n>h` line from
`scripts/check_prod.py`, and the GitHub run URL that ran it.

## render-cold-start-storm

**Trigger:** the Render free instance has slept, so the first requests of a cycle queue
behind the boot instead of being served.

**Detection signal:**
- `python -m scripts.warm --base-url <API_URL>` measures the hosted first answer; the
  cold start quoted in [DEPLOY.md](DEPLOY.md) is 30-50 s, and the script exits 1 above
  the 50 s it documents.
- `/health` first-byte latency is tens of seconds on the first call and under a second on
  the next: `curl -s -o /dev/null -w '%{time_total}\n' "$API_URL/health"`.

Locally the drill simulates the observable symptom: a TCP server accepts and never
replies, so ten concurrent GETs time out, the shape a sleeping instance produces. It does
not wake or touch the real Render service.

**Response:**
1. Follow "Cold start and keep-warm" in [RUNBOOK.md](RUNBOOK.md#1-operate):
   `python -m scripts.warm --base-url "$API_URL"` records the hosted number.
2. Switch the cron Worker to hourly mode with `make ingest-every HOURS=1`; it then pings
   `/health` every ten minutes (see [DEPLOY.md](DEPLOY.md)).
3. Confirm the next `python -m scripts.warm --base-url "$API_URL"` exits 0 within 50 s.
4. Re-run the drill offline with `python -m scripts.incident_drill`; the
   `render_cold_start_storm` case asserts all ten 0.5 s probes time out and the whole
   case finishes in under five seconds.

**Rollback:** `make ingest-every HOURS=24` returns the Worker to daily mode and spends
fewer free hours.

**Escalation:** repo owner (single operator), SEV3, if the hosted number stays above 50 s
while the keep-warm dispatch runs. Attach the `scripts.warm` output line, the
`time_total` from the first and second `curl` calls with their `X-Request-ID` headers, and
the cron Worker's GitHub or Cloudflare run URL for the keep-warm slot.

## cron-dispatch-failure

**Trigger:** the cron Worker throws instead of dispatching a workflow, or GitHub's
dispatch endpoint answers a status other than 204.

**Detection signal:**
- Cloudflare `npx wrangler tail` prints `dispatch <job> <status>: <body>`; that line is
  the throw at `ops/ingest-cron/index.mjs` for any status other than 204.
- No new Actions run exists for the current slot:
  `gh run list --workflow=ingest.yml --limit 5`.
- `python -m scripts.check_prod.py` then fails with `::error::no new event for <n>h`.

Locally the drill simulates the observable symptom: a local HTTP server answers 500 and
the Worker's `status != 204` check turns it into a dispatch error. It does not call
GitHub or deploy the Worker.

**Response:**
1. Follow "Production tasks" in
   [RUNBOOK.md](RUNBOOK.md#0-production-pages--render--supabase--actions): renew the
   token from `ops/ingest-cron` with `npx wrangler secret put GH_TOKEN`, then redeploy
   with `npx wrangler deploy`.
2. Start one cycle by hand with `gh workflow run ingest.yml`; expected: a new run appears
   in `gh run list --workflow=ingest.yml --limit 1`.
3. Watch the next slot with `npx wrangler tail`; expected: no `dispatch ... <status>`
   error.
4. Re-run the drill offline with `python -m scripts.incident_drill`; the
   `cron_dispatch_failure` case asserts the 500 is detected and that 204 passes.

**Rollback:** `npx wrangler secret put GH_TOKEN` with the previous token restores the old
secret.

**Escalation:** repo owner (single operator), SEV2, when the next 10-minute slot still
fails after the token is replaced. Attach the Worker tail text (`dispatch <job> <status>:
<body>`), the missing Actions run query output, the `::error::no new event` line, and the
`X-Request-ID` / `correlation_id` of the last successful `/api/health` call.

## feed-outage

**Trigger:** one upstream feed endpoint fails or disappears, so its `world/<key>` source
stops producing while the rest of the cycle continues.

**Detection signal:**
- `GET /api/health` `source_health` entry `world/<key>` has status `WARN` with
  `last_error` set, or status `STALE` once `fetched_at` passes
  `source_stale_after_minutes` (`worker/health.py` derives STALE at read time).
- `source_health.last_error` holds the fetch exception for that feed.
- `scrape_runs` has the cycle row (`worker/health.py`), so the failure is one feed rather
  than the whole run.

**Response:**
1. Follow "A source shows STALE" and "A source shows WARN" in
   [RUNBOOK.md](RUNBOOK.md#3-common-incidents): read the worker log for
   `[world/<key>]` and the `source_health.last_error` value.
2. Force one cycle with `gh workflow run ingest.yml`; expected: the feed's row flips back
   to `OK` and the other sources stay `OK`.
3. If the URL is dead, fix it in `finscrape/fetchers/world/feeds.py` per
   [DATA_SOURCES.md](DATA_SOURCES.md); a feed that must stay off is disabled by its own
   ingestor switch, not by editing the world registry.
4. Re-run the drill offline with `python -m scripts.incident_drill`; the `feed_outage`
   case points `WorldRSSScraper.feeds` at `http://localhost:1/rss` with the fetch seam
   refusing and asserts `scraper.feed_health` records the error the worker stores as WARN.

**Rollback:** revert the one `feeds.py` URL line to the previous endpoint and redeploy
the worker.

**Escalation:** repo owner (single operator), SEV2, when the feed is still STALE after two
cycles or its URL answers 404. Attach the `source_health` row (`source`, `status`,
`last_error`, `fetched_at`), the `X-Request-ID` / `correlation_id` of the `/api/health`
call, the failing feed URL, and the verbatim fetch error text.
