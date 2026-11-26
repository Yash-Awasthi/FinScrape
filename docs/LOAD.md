# Load test: the read paths at 50 rps

plan M2.5 asks for a measured ceiling rather than a hope. This is the result of
`python -m scripts.loadtest`, run against one Granian/uvicorn worker on a laptop-class
machine with Postgres 18 on the same host. The numbers are only meaningful as a *comparing*
baseline — the point is the shape of the curve and which endpoint bends first.

## How it runs

```bash
# 1. the API, against the seeded test database, rate limit off
WORLDFIN_DATABASE_URL=postgresql://.../worldfin_test WORLDFIN_RATE_LIMIT_PER_MIN=0 \
  uv run -p 3.14 --group server --group dev python -m uvicorn server.main:app --port 8010

# 2. open-loop load at the target rate
python -m scripts.loadtest --base-url http://127.0.0.1:8010 --rps 50 --seconds 10
```

The driver is open-loop: request _i_ is scheduled at `i/rps` from the start. A slow endpoint
therefore shows up as a growing queue (real latency) instead of being hidden by the client
waiting for each response. 500 requests over the three endpoints, printed as p50/p95/p99 and
a named bottleneck.

## Result: 50 rps

| endpoint | n | 5xx | p50 | p95 | p99 |
|---|---|---|---|---|---|
| `/api/events?limit=50` | 167 | 0 | 7 ms | **9 ms** | 78 ms |
| `/api/scenarios` | 167 | 0 | 6 ms | **9 ms** | 28 ms |
| `/api/market/quotes` | 166 | 0 | 6 ms | **8 ms** | 18 ms |

`bottleneck: no bottleneck at this rate: worst p95 is /api/events?limit=50 at 9 ms`

The same run at 100 rps and 125 rps still holds (worst p95 14 ms and 17 ms).

## What broke first, and what fixed it

The first run of this test was the useful one. With the same rate, before the quote path was
made single-flight:

| endpoint | p50 | p95 | max |
|---|---|---|---|
| `/api/market/quotes` | 579 ms | **8469 ms** | 8632 ms |
| `/api/events?limit=50` | 359 ms | 1688 ms | 1854 ms |
| `/api/scenarios` | 336 ms | 1557 ms | 1776 ms |

**The first bottleneck was the quote threadpool, not Postgres.** Every request started its own
`yfinance` download inside `asyncio.to_thread`; the default pool (~16 threads) saturated, each
blocked download burned the full `WORLDFIN_UPSTREAM_TIMEOUT_S` budget, and the event loop
queue behind it dragged `/api/events` from 9 ms to 1.7 s p95. Two changes removed it:

1. **A failure window** (`FINSCRAPE_QUOTE_FAIL_TTL`, default 30 s) in `finscrape/market_data.py`
   — a host that just failed is not retried by every request for the next 30 seconds.
2. **Single-flight** in `server/routes/market.py` — while one download is in progress, other
   callers get the last snapshot (`cached_quotes`) instead of queueing for their own.

After both, the tape's p95 went from 8.5 s to 8 ms at the same rate.

## The ceiling

At **150 rps** open-loop, one process stops keeping up and the queue grows without bound:

| endpoint | p50 | p95 | max |
|---|---|---|---|
| `/api/events?limit=50` | 39.5 s | 43.3 s | 62.5 s |
| `/api/scenarios` | 39.4 s | 43.3 s | 62.2 s |
| `/api/market/quotes` | 39.4 s | 43.3 s | 61.9 s |

No 5xx: the server accepted everything and fell behind, which is the expected shape for a
single worker with no concurrency limit in front of it. **The ceiling is the process, not the
database**: `/api/events` (the heaviest query) degrades at the same rate as the others, and
the knee is sharp between 125 and 150 rps.

To go past it, in order of what the numbers actually justify:

1. More workers (`WEB_CONCURRENCY`), which needs `WORLDFIN_REDIS_URL` for the rate limiter —
   the settings refuse to boot >1 replica without it.
2. A response cache on `/api/events` and `/api/scenarios` for the poll interval; both are
   already cacheable and already emit ETags, so a 304 costs nothing.
3. A connection-pool review only after the above: the pool (10) was never the limiter here.

The trigger that earns each of those steps, and its rollback, is [docs/SCALING.md](SCALING.md).

## Reproducing

`make loadtest` runs the 50 rps case against a server already listening on `--base-url`. The
published table above is from 2026-11-24; re-run it after any change to the quote path or the
`/api/events` query and update this file, because a load test nobody repeats is a story.
