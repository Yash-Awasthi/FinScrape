# Security & hardening

How the WorldFin backend defends its trust boundaries. All knobs are env vars (see
`.env.example`); defaults are safe for the demo and tightenable for production.

## Authentication

- The four **mutating** routes (`/api/ingest`, …) require an API key — `X-API-Key: <key>`
  or `Authorization: Bearer <key>` (`server/auth.py`). Everything else is read-only.
- Key comes only from `FINSCRAPE_API_KEY` (env). No key is ever hard-coded or logged.
- Rotate by changing the env var and restarting; no DB migration needed.

## Rate limiting

- Per-client **sliding-window** limiter (`server/rate_limit.py`), `WORLDFIN_RATE_LIMIT_PER_MIN`
  (default 120; `0` disables). Past the threshold → **429** with a `Retry-After` header.
- Client identity = first `X-Forwarded-For` hop (behind nginx) else the peer IP.
- In-memory, process-local. Ceiling: a single API replica. Multi-replica upgrade path is a
  Redis sorted-set window keyed on `WORLDFIN_REDIS_URL` — noted in the module docstring.

## SSRF guard

- `/api/rss-proxy` only fetches URLs from the **feed registry** (gated by feed key — no
  arbitrary user URL reaches the fetcher).
- Defense in depth: `server/ssrf.py` resolves the host and rejects any non-public address
  (loopback / private / link-local / reserved, incl. the `169.254.169.254` cloud-metadata
  endpoint) **before** the request *and* on **every redirect hop** — a registry host that
  302s to a private IP is still refused. Only `http`/`https` schemes are allowed.

## Security headers / CSP

- Every API response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`, and a locked-down
  `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'`
  (API serves only JSON — no inline assets). `Strict-Transport-Security` is opt-in via
  `WORLDFIN_ENABLE_HSTS` (turn on only behind TLS).
- The static SPA gets its own (looser) CSP + the same hardening headers from `web/nginx.conf`.

## CORS

- `WORLDFIN_CORS_ORIGINS` is a comma-separated allowlist (`server/app.py`). Default `*` is for
  local dev; set explicit origins in production.

## Input validation

- Every request body/query is a Pydantic model or a bounded `Query(...)` (`ge`/`le` clamps on
  every `limit`), so out-of-range or malformed input is rejected at the boundary with a 422.

## Resilience

- **Circuit breakers** (`server/circuit.py`) wrap the flaky upstreams (CoinGecko, RSS). After
  N consecutive failures the breaker opens and fails fast for `reset_after_s`, then half-opens
  one probe — a dead upstream can't burn a threadpool slot + 15s timeout on every request. The
  panel degrades gracefully (empty list), the app stays up.
- **Probes:** `GET /health` is **liveness** (always 200; `degraded` if the DB is down).
  `GET /ready` is **readiness** — 200 only when the DB pool answers, else **503** so an
  orchestrator stops routing to a half-open replica.
- **Error envelopes:** every error path returns a uniform `{"error": {"status", "message"}}`;
  unhandled exceptions are logged and returned as a generic 500 (no stack trace leaks).

## Performance

- **ETag / 304:** GET JSON responses carry a weak `ETag`; a matching `If-None-Match` returns
  **304** with no body (`WORLDFIN_ENABLE_ETAG`, default on).
- **Tiered TTL cache** (`server/cache.py`): fast/medium/slow tiers in front of the network
  upstreams so repeated reads don't re-hit CoinGecko/RSS.
- **SPA code-split:** the globe.gl (+three.js) vendor chunk (~1.8MB) is lazy-loaded on its own
  (`web/src/main.ts` dynamic `import`), so first paint ships ~7KB gzip instead of ~540KB; the
  globe pops in when its chunk arrives.
- DB indexes for every hot filter/sort (`server/migrations/0001_init.sql`): `timestamp`,
  `verdict`, `event_type`, `created_at`, GIN on `tickers`. **`EXPLAIN ANALYZE` (8k rows)**
  confirms Index/Index-Only scans on feed, verdict-filter, day-range count, and by-id. The two
  full-table aggregates (dates GROUP-BY-day, markets ticker rollup) seq-scan by design — no
  index applies — and run sub-6ms at that scale.

## Verify

```bash
# unit + middleware integration (no DB):
uv run -p 3.13 --group server --group dev pytest tests/server/test_hardening.py -q
```
- **429 past threshold:** `WORLDFIN_RATE_LIMIT_PER_MIN=3`, fire 5 requests → 3×200, 2×429
  (`test_rate_limit_returns_429_with_retry_after`).
- **SSRF rejected:** a private/metadata IP is refused (`test_assert_public_url_*`).
- **304 cache hit:** repeat a GET with the returned `ETag` → 304 (`test_etag_then_304`).
- **Dead source doesn't take down the app:** breaker opens and the route returns an empty
  payload instead of erroring (`test_circuit_opens_then_half_opens_then_recovers`).

Quick manual load check (confirms cache/304 + rate limit under concurrency):
```bash
# 200 requests, 20 concurrent — expect a burst of 200s then 429s once the window fills
seq 200 | xargs -P20 -I{} curl -s -o /dev/null -w "%{http_code}\n" localhost:8010/api/feeds | sort | uniq -c
```
