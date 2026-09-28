"""Cross-process new-event fan-out via Redis pub/sub (Phase 12 seam).

The in-process WS hub (`server/ws.py`) only reaches clients of the SAME process, so the
separate worker process can't push `new_events` to API WS clients. When Redis is enabled
(`WORLDFIN_REDIS_URL` set), the worker PUBLISHES to a channel and the API SUBSCRIBES and
re-broadcasts to its hub. When Redis is disabled both calls are **no-ops** — the worker
stays silent to live clients (API-side ingest still broadcasts directly), so single-process
runs need no Redis.

`redis` is imported lazily so the lean images don't carry the dep unless it's enabled.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from server.settings import get_settings

log = logging.getLogger("worldfin.pubsub")

CHANNEL = "worldfin:events"


async def publish(message: dict) -> bool:
    """Publish a message to subscribers. Returns True if it was sent, False if Redis is
    disabled or the publish failed (best-effort — never raises into the caller)."""
    settings = get_settings()
    if not settings.redis_enabled:
        return False
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        try:
            await client.publish(CHANNEL, json.dumps(message, default=str))
        finally:
            await client.aclose()
        return True
    # Fan-out is optional; ingest goes on.
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        log.warning("pubsub publish failed: %s", exc)
        return False


RECONNECT_DELAY_S = 5.0


async def _subscribe_once(handler: Callable[[dict], Awaitable[None]]) -> None:
    """One connection's lifetime: subscribe, forward messages, close on the way out."""
    import redis.asyncio as aioredis

    settings = get_settings()
    client = aioredis.from_url(settings.redis_url)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(CHANNEL)
        log.info("pubsub: subscribed to %s", CHANNEL)
        async for raw in pubsub.listen():
            if raw.get("type") != "message":
                continue
            try:
                await handler(json.loads(raw["data"]))
            # One bad message keeps the stream.
            except Exception as exc:  # noqa: BLE001  # pragma: no cover
                log.warning("pubsub handler failed: %s", exc)
    finally:
        await pubsub.aclose()
        await client.aclose()


async def subscribe_forever(handler: Callable[[dict], Awaitable[None]]) -> None:
    """Subscribe and forward each decoded message to `handler` until cancelled.

    No-op when Redis is disabled. Otherwise it reconnects: this runs as a detached
    task, so letting a dropped connection end it would silently strip worker-pushed
    events from every WS client in the process for the rest of its life.
    """
    if not get_settings().redis_enabled:
        return
    while True:
        try:
            await _subscribe_once(handler)
        except asyncio.CancelledError:
            raise
        # Reconnect on any drop.
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            log.warning("pubsub subscribe failed (%s); retrying", exc)
        await asyncio.sleep(RECONNECT_DELAY_S)
