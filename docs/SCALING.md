# Scaling path

The four stages plan M6.3 names, in the order the measurements justify. Each stage
states the trigger that earns it, the one change it makes, and how to go back. A stage
is not taken before its trigger has been measured: "it might get busy" is a forecast,
not a trigger.

| Stage | Adds | Trigger |
|---|---|---|
| 0 (today) | one API process, in-process state | - |
| 1 | Redis | a second process or replica is wanted, for availability or for the ceiling below |
| 2 | multiple API replicas | Redis in place and sustained peak above one process |
| 3 | Postgres connection pooling | summed replica pools near the database's connection limit |

## Stage 0: one API replica

Today the API is one Granian process on Render. The rate limiter, the response cache and
the WebSocket fan-out are all in-process, which is why one replica is the safe shape
rather than a temporary one ([ADR 0001](adr/0001-no-redis-yet.md)). The asyncpg pool is
`min_size=2, max_size=10` per process ([`server/db.py`](../server/db.py)).

What the read paths actually do on that shape, from [`docs/LOAD.md`](LOAD.md):

| Offered rate, open loop | Worst p95 | Outcome |
|---|---|---|
| 50 rps | 9 ms | flat |
| 100 rps | 14 ms | flat |
| 125 rps | 17 ms | flat |
| 150 rps | 43 s | process stops keeping up; no 5xx, the queue grows |

The knee is between 125 and 150 rps, and the limiter is the process, not Postgres: the
heaviest endpoint (`/api/events`) bends at the same rate as the others. The p95 target
this path is measured against is the 400 ms on `/api/events` in [plan.md](../plan.md)
M6.1.

Cost of staying here: Render free spins down after 15 minutes idle (~30-50 s cold start,
[`docs/COST.md`](COST.md)); Starter is $7/month and never sleeps. Paying that is a cost
decision, not a scaling stage.

**Leave stage 0 when** peak read traffic is above roughly 125 rps, or p95 at peak is
above 400 ms, or a second process is wanted for availability (a deploy currently drops
in-flight requests).

## Stage 1: Redis

**Trigger:** any of the following.

- a second API process or replica is wanted, for either reason above;
- the rate-limit window must be shared: a burst spread over two processes otherwise
  multiplies the per-IP allowance.

The production startup guard already refuses the unsafe configuration: with
`WORLDFIN_ENV=production` and `WEB_CONCURRENCY > 1` without `WORLDFIN_REDIS_URL` the API
does not boot ([`server/settings.py`](../server/settings.py), `production_problems`).

**Change:** set `WORLDFIN_REDIS_URL`. `RedisLimiter` takes over the sliding window,
the cache becomes shared and the WebSocket broadcast uses pub/sub
([`server/rate_limit.py`](../server/rate_limit.py), `server/cache.py`, `server/ws.py`).
The compose stack has the same service behind its `redis` profile.

**Rollback:** unset `WORLDFIN_REDIS_URL` and set `WEB_CONCURRENCY=1` together. Redis
alone raises no ceiling; it only removes the reason the second process was refused.

## Stage 2: multiple API replicas

**Trigger:** Redis is in place, and the measured peak is above the one-process knee
(125-150 rps, [`docs/LOAD.md`](LOAD.md)) or p95 at peak is above 400 ms.

Before raising the count, confirm the load is the API and not an upstream: the quote
path was the first thing to saturate (8.5 s p95 at 50 rps) and is now single-flight with
a failure window. A replica count that answers an upstream stall multiplies the waiting,
not the capacity.

**Change:** raise `WEB_CONCURRENCY` (or the Render instance count). Each replica costs
another Starter instance ($7/month of the $32 total in [`docs/COST.md`](COST.md)) and
opens up to 10 more database connections.

**Rollback:** `WEB_CONCURRENCY=1`. Redis stays; nothing else changes.

## Stage 3: Postgres connection pooling

**Trigger:** the summed `max_size` of every replica pool (10 each) approaches the
database's `max_connections`, or connection acquisition shows up in the p95 while
queries themselves are fast.

The provider ceiling has to be read from the database rather than assumed: run
`SHOW max_connections;` (and the pooler's limit if one is already enabled) and record it
in this file before multiplying replicas. On Supabase that number belongs to the plan
and is not in this repository, so it is a one-line owner check, not a guess.

**Change:** send the API through a transaction-mode pooler (Supabase's pooled port, or
PgBouncer in front of a self-hosted Postgres) and shrink the per-process pool. Prepared
statements need care in transaction mode; asyncpg defaults are fine once statement
caching is disabled.

**Rollback:** point `WORLDFIN_DATABASE_URL` back at the direct port. The pool size is
the same setting on both paths.

Do this last: at 125 rps the pool was never the limiter, so pooling early buys a new
component and no capacity.

## What each stage needs before it ships

- Per-endpoint p95, 429 counts and database connection count are on the dashboard
  ([`docs/RUNBOOK.md`](RUNBOOK.md) section 2), so the trigger is observed rather than
  guessed.
- The load test is re-run after the change (`.github` has no load job; `make loadtest`
  against a local stack) and [`docs/LOAD.md`](LOAD.md) gets the new row.
- The rollback above is written into the change that takes the stage, and the stage's
  cost is added to [`docs/COST.md`](COST.md) in the same commit.

## Evidence

- [`docs/LOAD.md`](LOAD.md): 9 ms at 50 rps, 17 ms at 125 rps, queue collapse at 150 rps;
  the quote path as the measured first bottleneck.
- [`server/settings.py`](../server/settings.py): the production guard that refuses
  `WEB_CONCURRENCY > 1` without Redis.
- [`server/db.py`](../server/db.py): the 2/10 pool.
- [`docs/COST.md`](COST.md): Render free/Starter and Supabase Free/Pro ceilings.
- [ADR 0001](adr/0001-no-redis-yet.md): why in-process state is the current decision and
  what reopens it.
