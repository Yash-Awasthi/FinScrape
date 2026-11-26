# 0001 No Redis yet

## Status

Accepted, 2026-11-26.

## Context

Rate limiting, the tiered cache and WebSocket fan-out all need shared state once more than one API process serves traffic. Today the API runs as a single replica, so in-process state is enough, and a Redis dependency would add an operational component without a current need.

## Decision

Keep state in-process and treat Redis as an optional, documented seam rather than a dependency. `Limiter` in [rate_limit.py](../../server/rate_limit.py) uses a deque in the API process and is the default; its ceiling is a single API replica. `RedisLimiter` implements the same sliding window in a shared Redis sorted set and is enabled by `WORLDFIN_REDIS_URL`. The API refuses to start in production with `WEB_CONCURRENCY > 1` and no Redis, so the unsafe configuration cannot be deployed by accident.

The cache follows the same rule: [cache.py](../../server/cache.py) is process-local with no Redis, and [ws.py](../../server/ws.py) broadcasts in-process on a single replica, switching to Redis pub/sub fan-out when the settings report Redis enabled.

[STACK.md](../STACK.md) lists Redis as optional at floor version 8, only needed when `WEB_CONCURRENCY > 1`, and records "No Redis in production. One API replica" among the things deliberately kept old. [RUNBOOK.md](../RUNBOOK.md) repeats the scaling path in its scaling notes.

## Consequences

The deployment has one fewer service to run, monitor and pay for, and the single-replica ceiling is explicit rather than discovered. Rate limits, cache entries and WebSocket connections are per process, so a second replica without Redis would multiply limits and split live updates, which is why the production startup guard refuses that combination.

The documented scaling path in [plan.md](../../plan.md) M6.3 is single replica, then Redis, then multiple API replicas, then Postgres connection pooling. `WORLDFIN_REDIS_URL` is the seam: setting it turns on the shared limiter and Redis fan-out without a rewrite.

Revisit this decision when sustained read traffic exceeds what one replica can serve, or when a second API replica is wanted for availability. At that point Redis becomes required and the production startup guard changes with it.

## Evidence

- [rate_limit.py](../../server/rate_limit.py): `Limiter` and `RedisLimiter`, the latter enabled by `WORLDFIN_REDIS_URL`.
- [cache.py](../../server/cache.py): process-local, no Redis, ceiling is a single replica.
- [ws.py](../../server/ws.py): in-process broadcast, Redis pub/sub fan-out when `get_settings().redis_enabled`.
- [STACK.md](../STACK.md): Redis optional, floor 8, only for `WEB_CONCURRENCY > 1`.
- [RUNBOOK.md](../RUNBOOK.md): scaling notes, multi-replica needs Redis.
- [plan.md](../../plan.md) M6.3: single replica, Redis, multiple replicas, connection pooling.
