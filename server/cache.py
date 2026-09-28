"""Tiny in-process TTL cache with named tiers (fast / medium / slow).

Replaces the ad-hoc dict cache in routes/data.py. One module so every cached read
shares the same eviction + tier semantics. Values are whatever the producer returns
(already-serialized dicts/lists here).

ponytail: process-local, no Redis. Ceiling = single replica; multi-replica wants a
shared store. Upgrade path: swap `_store` get/set for Redis GET/SETEX keyed the same.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# Tier TTLs in seconds — pick by how fast the upstream truth moves.
FAST = 30  # volatile (crypto/markets quotes)
MEDIUM = 120  # semi-static (RSS feeds)
SLOW = 600  # rarely-changing (registries, rollups)

# Ceiling on live entries: some keys carry a caller-supplied ticker, so the key space
# is open-ended and the store is dropped wholesale at the limit instead of growing.
_MAX_ENTRIES = 4096

_store: dict[str, tuple[float, object]] = {}

# One lock per in-flight key. Without it every concurrent miss runs `produce()`,
# which for /api/scenarios is a full Ollama embedding pass per caller.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


MISSING = object()  # distinguishes "no live entry" from a cached None


def peek(key: str) -> object:
    """Live value for `key`, or `MISSING`. Lets a caller skip the work that
    builds `produce`'s inputs, not just `produce` itself."""
    hit = _store.get(key)
    return hit[1] if hit and hit[0] > time.monotonic() else MISSING


def get_or_set(key: str, ttl: float, produce: Callable[[], object]) -> object:
    """Return cached value for `key`, or call `produce()` and cache it for `ttl`s.

    Concurrent misses on one key collapse to a single `produce()` call; the
    others wait and read the stored result.
    """
    cached = peek(key)
    if cached is not MISSING:
        return cached
    try:
        with _lock_for(key):
            cached = peek(key)  # another caller may have produced it while we waited
            if cached is not MISSING:
                return cached
            now = time.monotonic()
            if len(_store) >= _MAX_ENTRIES:
                for stale in [k for k, (exp, _) in _store.items() if exp <= now]:
                    del _store[stale]
                if len(_store) >= _MAX_ENTRIES:
                    _store.clear()
            value = produce()
            _store[key] = (now + ttl, value)
            return value
    finally:
        with _locks_guard:
            _locks.pop(key, None)  # a later miss makes a fresh lock


def clear() -> None:
    """Drop everything (tests / manual cache-bust)."""
    _store.clear()
