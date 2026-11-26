# 0006 WebSocket fan-out

## Status

Accepted, 2026-11-26.

## Context

The live feed is a WebSocket the API process serves. [ws.py](../../server/ws.py) holds one `WSHub` per process, so a broadcast reaches only the clients connected to that process. The API-side ingest route in [events.py](../../server/routes/events.py) broadcasts on that hub directly, which is enough while the worker and the API share a process boundary or while only API writes reach the feed.

The worker does not share that process. It runs as a separate job and writes rows to Postgres, so its `new_events` frames reach nobody unless a channel crosses the process boundary. [pubsub.py](../../server/pubsub.py) is that channel: `publish` and `subscribe_forever` over Redis, with `CHANNEL = "worldfin:events"` as the one fixed topic. Both are no-ops when Redis is disabled, so the single-replica deployment needs no Redis and pays nothing for the seam.

Two options were on the table for the multi-process path. The first is Redis pub/sub, already implemented and already the seam named in [ADR 0001](0001-no-redis-yet.md). The second is Cloudflare Durable Objects. The SPA is static on Cloudflare Pages ([ADR 0003](0003-static-spa.md)), and the API is a Python process on Render, so a Durable Object would sit beside the API as a second runtime with its own client, deployment and billing, to carry the same JSON frames. Cloudflare Durable Objects are a paid product on the Workers platform; the free-tier stack in [DEPLOY.md](../DEPLOY.md) is built to stay at zero.

## Decision

Redis pub/sub is the multi-process WebSocket fan-out path. The worker publishes to the fixed topic `worldfin:events` exported as `CHANNEL` from [pubsub.py](../../server/pubsub.py), and every API process runs `subscribe_forever(hub.broadcast)` from its lifespan hook, so a published frame is re-broadcast to that process's clients. The topic is fixed, not per-process or per-client: one channel carries every `new_events` frame and no subscriber filters by topic.

In-process broadcast stays the default and the only path on a single replica. [ws.py](../../server/ws.py) keeps the module-level `hub` and its `broadcast`; with Redis disabled, `publish` returns `False` and `subscribe_forever` returns immediately, leaving the API-side ingest broadcast untouched and the worker silent to live clients.

Cloudflare Durable Objects are rejected. The SPA is a static build ([ADR 0003](0003-static-spa.md)), the API is a Python process on Render, and a Durable Object would add a second runtime plus a paid product to deliver the same messages that Redis already delivers through a code path that exists.

Enablement is `WORLDFIN_REDIS_URL`, the same seam as the shared rate limiter in [ADR 0001](0001-no-redis-yet.md). Setting it turns on the shared limiter and the pub/sub fan-out together; unsetting it leaves both in their in-process defaults. No new setting is introduced.

## Consequences

Without Redis, each API process's hub is private. A worker-ingested row is written to Postgres and appears on the dashboard through the refresh loop's `GET /api/stats` poll, which compares `last_update` and then fetches `GET /api/events?since_id=`, rather than as a live frame. Live frames are still correct for writes that go through the API ingest route, because that route broadcasts on the local hub.

With Redis set, worker frames reach every API process and are re-broadcast to its clients, so the poll becomes a fallback rather than the only path for worker rows. Fan-out stays best-effort: a failed publish is logged and dropped, ingest continues, and the poll still covers the gap.

What stays correct either way: the hub drops dead sockets on send, the subscriber reconnects after a dropped connection instead of ending for the life of the process, and a message the handler rejects does not stop the stream. The API-side ingest broadcast, the reverse-proxy WebSocket route and the SPA's reconnect logic do not change.

The cost of enabling Redis is one more service to run, monitor and pay for, plus a connection per API process. The single-replica deployment does not need it, which is why it stays off.

Revisit this decision when a second API replica is deployed, when worker-ingested rows must appear without the poll interval, or when Redis is enabled in production for the shared limiter. At that point the fan-out is already wired and the decision is whether to keep the poll alongside it.

## Evidence

- [pubsub.py](../../server/pubsub.py): `CHANNEL = "worldfin:events"`, `publish`, `subscribe_forever`, both no-ops when Redis is disabled.
- [ws.py](../../server/ws.py): in-process `WSHub`, module-level `hub`, `broadcast` to local clients.
- [events.py](../../server/routes/events.py): `/api/events` ingest broadcasts `new_events` on the local hub after insert; `/api/stats` is the poll endpoint.
- [STACK.md](../STACK.md): Redis optional at floor 8, only needed when `WEB_CONCURRENCY > 1`.
- [DEPLOY.md](../DEPLOY.md): worker rows reach the dashboard through the refresh poll; the free-tier stack runs without Redis.
- [ADR 0001](0001-no-redis-yet.md): `WORLDFIN_REDIS_URL` is the seam for the shared limiter and fan-out.
