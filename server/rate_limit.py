"""Per-client sliding-window rate limiter.

In-memory by design: one API replica is the FinScrape demo topology, so a process-local
deque of hit timestamps is the whole limiter — no Redis round-trip on the hot path.

ponytail: in-memory only. Ceiling = a single API replica (each process keeps its own
window). Upgrade path for >1 replica: back `Limiter.hit` with a Redis sorted-set
(ZADD now / ZREMRANGEBYSCORE < now-window / ZCARD) keyed on `settings.redis_url`.
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
