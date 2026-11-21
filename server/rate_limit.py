"""Per-client sliding-window rate limiter.

Two backends behind one `hit(key)` contract (plan M1.6):

* `Limiter` — in-memory deque, the default. One process, one window: the ceiling is a
  single API replica.
* `RedisLimiter` — the same sliding window in a Redis sorted set, shared by every
  replica. Enabled by `WORLDFIN_REDIS_URL`; the API refuses to start in production with
  `WEB_CONCURRENCY > 1` and no Redis, so the documented ceiling can never be quietly
  multiplied by the replica count.
"""

from __future__ import annotations

import time
from collections import deque
from ipaddress import ip_address

# Upper bound on tracked clients. Reached only by a flood of distinct real source
# addresses; tracking stops rather than letting the map grow without limit.
MAX_TRACKED_CLIENTS = 50_000


class Limiter:
    """Sliding-window counter. `hit(key)` returns (allowed, retry_after_seconds)."""

    def __init__(self, limit_per_min: int, window_s: float = 60.0) -> None:
        self.limit = limit_per_min
        self.window = window_s
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float | None = None) -> tuple[bool, int]:
        if self.limit <= 0:  # disabled
            return True, 0
        now = time.monotonic() if now is None else now
        q = self._hits.get(key)
        if q is None:
            if len(self._hits) >= MAX_TRACKED_CLIENTS:
                self._prune(now)
                if len(self._hits) >= MAX_TRACKED_CLIENTS:
                    return True, 0  # at capacity — stop tracking instead of growing
            q = self._hits[key] = deque()
        cutoff = now - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= self.limit:
            # retry once the oldest hit ages out of the window
            retry = max(1, int(q[0] + self.window - now) + 1)
            return False, retry
        q.append(now)
        return True, 0

    def _prune(self, now: float) -> None:
        """Drop every client whose newest hit already left the window."""
        cutoff = now - self.window
        for key in [k for k, d in self._hits.items() if not d or d[-1] <= cutoff]:
            del self._hits[key]


class RedisLimiter:
    """The same sliding window, shared by every replica.

    One sorted set per client: score = hit time, member = a unique token. The three
    commands run in one pipeline so two replicas cannot each see a full window and
    both admit a request:

        ZREMRANGEBYSCORE key -inf (now-window)   drop aged-out hits
        ZCARD key                               count what is left
        ZADD key now token   (+ EXPIRE)         record this hit when admitted

    Uses the wall clock, not `time.monotonic`: the window lives in a shared server, so
    every replica has to agree on what "now" is.
    """

    def __init__(
        self,
        url: str,
        limit_per_min: int,
        window_s: float = 60.0,
        prefix: str = "worldfin:rl:",
        client=None,
    ) -> None:
        self.limit = limit_per_min
        self.window = window_s
        self.prefix = prefix
        self._client = client
        self._url = url

    @property
    def client(self):
        """Lazy client so importing this module never needs the redis package."""
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def hit(self, key: str, now: float | None = None) -> tuple[bool, int]:
        if self.limit <= 0:  # disabled
            return True, 0
        now = time.time() if now is None else now
        bucket = f"{self.prefix}{key}"
        cutoff = now - self.window
        db = self.client
        await db.zremrangebyscore(bucket, "-inf", cutoff)
        count = await db.zcard(bucket)
        if count >= self.limit:
            oldest = await db.zrange(bucket, 0, 0, withscores=True)
            stamp = float(oldest[0][1]) if oldest else cutoff
            retry = max(1, int(stamp + self.window - now) + 1)
            return False, retry
        await db.zadd(bucket, {f"{now}:{key}": now})
        await db.expire(bucket, int(self.window) + 1)
        return True, 0


async def hit(limiter, key: str, now: float | None = None) -> tuple[bool, int]:
    """`hit` for either backend — the middleware must not care which one it got."""
    result = limiter.hit(key, now)
    if hasattr(result, "__await__"):
        return await result
    return result


def _is_proxy_peer(host: str) -> bool:
    """True only when `host` is an address a reverse proxy of ours listens on.

    Restricted to loopback, RFC1918 / IPv6 unique-local, and link-local space — the
    ranges a proxy on our own host or network occupies. Anything else, including a
    peer that is not an IP literal at all, is treated as the real client, so a header
    only the client could have written never selects the limiter key.
    """
    try:
        ip = ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def client_key(request) -> str:
    """Rate-limit identity: the caller IP, never a header the caller wrote itself.

    `X-Forwarded-For` is read only when the direct peer is a proxy we operate, and
    then only its rightmost hop — the entry the nearest proxy appended. The leftmost
    hop is written by the original sender and is spoofable by anyone, so trusting it
    would let one client present unlimited identities and never hit the limit.
    """
    peer = request.client.host if request.client else ""
    if peer and _is_proxy_peer(peer):
        xff = request.headers.get("x-forwarded-for")
        hops = [h.strip() for h in xff.split(",") if h.strip()] if xff else []
        if hops:
            return hops[-1]
    return peer or "unknown"
