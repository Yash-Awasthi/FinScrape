# FinScrape - Service Level Objectives

## Window

Monthly means the calendar month UTC. A breach is a measurement worse than the target that is sustained or observed in that window according to the per-SLO definition below; one stray sample does not count where the definition asks for a share over the whole month.

These targets are internal engineering budgets, not a customer contract. Only SLO 2 and SLO 4 have an automated check in-repo.

## 1. API availability: 99.5% monthly

**Definition.** Availability is the share of non-5xx responses among all responses to `/api/*` over the calendar month, counted server-side: successes divided by all `/api/*` responses. A 5xx is any status from 500 to 599.

**Measurement.** There is no hosted uptime monitor and no uptime history is recorded, so this target is `needs-verify` and cannot be reported today. Do not read a percentage here: none is measured. The nearest real signals are `GET /health` (liveness, always 200, with status `degraded` when the database is unreachable), `GET /ready` (200 only when the DB pool answers, 503 otherwise), and Render's own request logs, which are the only source for a retrospective count.

**Breach.** Month-to-date share of 5xx responses to `/api/*` exceeds 0.5%, meaning availability below 99.5%, once a counting source exists. Until then it is unmeasurable, so it is unproven rather than met.

## 2. /api/events latency: p95 at or under 400 ms

**Definition.** The 95th percentile of server-side round-trip latency for `GET /api/events?limit=50` at a fixed offered load of 50 requests per second.

**Measurement.** Run:

    python -m scripts.loadtest --base-url http://127.0.0.1:8010 --rps 50 --seconds 60

The script is [../scripts/loadtest.py](../scripts/loadtest.py). The endpoint list is at line 23, and the run prints per-endpoint p50/p95/p99 plus 5xx counts. The target is measured against a locally running API, not production.

**Breach.** p95 for `/api/events?limit=50` above 400 ms at the stated rate, or any 5xx from that endpoint during the run. The script exits 1 on errors.

## 3. Ingest freshness: newest event within 2× the ingest interval

**Definition.** The age of the newest row in `events` is at most 2× the configured `INGEST_EVERY_HOURS`, 24 by default, so 48 h. The check allows one extra hour of grace, `max_age_hours()` = 2 * INGEST_EVERY_HOURS + 1, because a single run that finds no news is not an outage. See [../scripts/check_prod.py](../scripts/check_prod.py).

**Measurement.** Run `python -m scripts.check_prod.py`. It prints `newest event <n>h old, database <n> MB` and exits 1 on staleness or on size above 450 MB; the worker evicts the oldest events above 400 MB, which leaves headroom under the 500 MB free-tier cap. Per-feed freshness is also readable at `GET /api/health`, whose `source_health` array reports OK / STALE / WARN / EMPTY per feed. See [../server/routes/health.py](../server/routes/health.py).

**Breach.** Newest event age above 2× the configured interval, which shows up as check_prod exit 1 with "no new event", or check_prod exit 1 for the 450 MB size guard. The size guard is a capacity alarm raised by the same run; it is not part of the 2× age budget.

## 4. Dashboard LCP: under 2.5 s

**Definition.** Largest Contentful Paint of the app shell on the BUILT single-page app, not the dev server. It is asserted by the Playwright test "LCP is inside the 2.5 s mid-range budget" in [../web/e2e/perf.spec.ts](../web/e2e/perf.spec.ts), which asserts lcp < 2500 ms after the Signal Feed panel is visible.

**Measurement.** Run:

    cd web && npx playwright test e2e/perf.spec.ts

This is a regression alarm measured on a developer machine. It is not a device certification and not a field p75; the spec file says exactly that.

**Breach.** LCP >= 2500 ms in that spec.

## Reading the four together

SLO 1 has no counting source, SLO 2 is a local load run, SLO 3 is a production job, and SLO 4 is a browser assertion, so the four are at different levels of evidence and should be read that way. The numbers worth trusting today are the ones a command prints on demand; the availability target stays `needs-verify` until a counting source exists. A green run of SLO 2, SLO 3, or SLO 4 is evidence for its own window only, and none of them substitutes for the missing availability count.

## Related

- [RUNBOOK.md](RUNBOOK.md)
- [SCALING.md](SCALING.md)
- [DEPLOY.md](DEPLOY.md)
- [LOAD.md](LOAD.md)
- [../scripts/loadtest.py](../scripts/loadtest.py)
- [../scripts/check_prod.py](../scripts/check_prod.py)
- [../web/e2e/perf.spec.ts](../web/e2e/perf.spec.ts)
- [../server/routes/health.py](../server/routes/health.py)
