# Security & hardening

How the FinScrape backend defends its trust boundaries. All knobs are env vars (see
`.env.example`); defaults are safe for the demo and tightenable for production.

## Authentication

- The four **mutating** routes (`POST /api/events` and the three alert-rule routes) require an
  API key — `X-API-Key: <key>` or `Authorization: Bearer <key>` (`server/auth.py`);
  `tests/server/test_route_auth.py` enumerates the app and fails if any other write route
exists without a guard. Everything else is read-only. `POST /api/telegram/webhook` is the
  one write path outside the key: it authenticates with `X-Telegram-Bot-Api-Secret-Token`
  and answers 200 either way, so a bad sender learns nothing.
- Key comes only from `FINSCRAPE_API_KEY` (env). No key is ever hard-coded or logged —
  `finscrape/logging_config.py` runs a `RedactSecrets` filter in front of every handler, so
  the values of `FINSCRAPE_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `ANALYZE_DISPATCH_TOKEN` and both DSNs are
  replaced with `<redacted>`, including inside tracebacks (`tests/test_log_redaction.py`).
- `.env` is gitignored, nothing named `.env` is tracked, and the history carries no
  live-looking key (`tests/test_secrets_hygiene.py`).
- Rotate by changing the env var and restarting; no DB migration needed.

## Rate limiting

- Per-client **sliding-window** limiter (`server/rate_limit.py`), `WORLDFIN_RATE_LIMIT_PER_MIN`
  (default 120; `0` disables). Past the threshold → **429** with a `Retry-After` header.
- Client identity = the peer IP; behind a proxy we operate (loopback/private/link-local) it is
  the rightmost `X-Forwarded-For` hop, the one our proxy appended. A header from a public peer
  is ignored so a caller cannot mint identities.
- Two backends, one contract: in-memory by default (one process, one window); with
  `WORLDFIN_REDIS_URL` set, a Redis sorted-set window shared by every replica. Production
  refuses to start with `WEB_CONCURRENCY > 1` and no Redis, so the ceiling cannot be silently
  multiplied by the replica count.

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

## Supply chain

Every dependency update arrives through one route and the gates are attached to it.

| Concern | Where it is enforced |
|---|---|
| Who opens an update PR | `.github/dependabot.yml` — `uv` + `pip` in one grouped PR, plus `npm`, `github-actions` and `docker`, weekly |
| What merges itself | `.github/workflows/dependabot-auto-merge.yml` — **patch only**, and only once every required check is green |
| How updates are bounded | `pyproject.toml` — `lxml` on a stable release, and `yfinance`/`pandas`/`spacy`/`scipy` carry `<next-major` ceilings, so a data-shape change is a reviewed PR |
| What ships | `Dockerfile.api`, `Dockerfile.worker`, `web/Dockerfile` — base images pinned by `@sha256:` digest as well as tag |
| What is installed | `dist/sbom.cdx.json`, generated from `uv.lock` by `python -m scripts.sbom`, attached to every release |
| What is vulnerable | `python -m scripts.audit --strict` (`pip-audit` + `npm audit --omit=dev`), with `security-audit-allowlist.json` carrying an owner and an expiry per tolerated advisory |

An allowlist entry without an expiry, or with one in the past, fails the audit — a
tolerated advisory is a scheduled decision rather than a comment nobody revisits.

## Verify

```bash
# unit + middleware integration (no DB):
uv run -p 3.14 --group server --group dev pytest tests/server/test_hardening.py -q
# supply chain: pins, digests, one update route, patch-only auto-merge, SBOM, allowlist
uv run -p 3.14 --group server --group dev pytest tests/test_supply_chain.py -q
# the audit itself (needs the network; pip-audit runs through uvx)
uv run -p 3.14 --group server --group dev python -m scripts.audit --strict
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
