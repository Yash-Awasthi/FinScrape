"""Fast, anti-bot-resistant HTTP fetch layer for plain-GET sources.

What it buys over raw requests/urllib:
- **TLS/browser impersonation** via curl_cffi — real browser JA3/TLS fingerprints
  and header sets, the cheapest effective Cloudflare/WAF bypass for read-only
  fetching. Profiles rotate when a host answers 403/429.
- **Conditional GET** — ETag/Last-Modified remembered per URL; unchanged feeds
  come back as 304 and cost almost nothing (fastest repeated news fetch).
- **Retry with jitter** on transient failures (timeouts, 429, 5xx), rotating the
  impersonation profile between attempts so a blocked fingerprint isn't retried.

Used by the RSS path; Scrapling-based scrapers keep their own stealth fetchers.
No new dependency: curl_cffi is already a core dependency of the vendored
Scrapling engine.
"""

from __future__ import annotations

import logging
import random
import threading
import time

import curl_cffi.requests as curl_requests
import requests

logger = logging.getLogger(__name__)

# Rotation order on block responses. Generic aliases (stable across curl_cffi
# versions); a profile the installed build doesn't know is skipped at runtime.
_PROFILES: tuple[str, ...] = ("chrome", "chrome120", "safari17_0", "edge101")

# url → (etag, last_modified, content)
_conditional_cache: dict[str, tuple[str, str, bytes]] = {}
_lock = threading.Lock()
_CACHE_MAX = 512


def _remember(url: str, etag: str, last_modified: str, content: bytes) -> None:
    with _lock:
        if len(_conditional_cache) >= _CACHE_MAX:
            _conditional_cache.pop(next(iter(_conditional_cache)))
        _conditional_cache[url] = (etag, last_modified, content)


def _cached(url: str) -> tuple[str, str, bytes] | None:
    with _lock:
        return _conditional_cache.get(url)


def fast_get(
    url: str,
    *,
    timeout: float = 15.0,
    retries: int = 2,
    use_cache: bool = True,
) -> bytes | None:
    """GET `url` with impersonation, conditional caching and jittered retries.

    Returns the response body bytes, or None when every attempt fails.
    """
    cached = _cached(url) if use_cache else None
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        profile = _PROFILES[attempt % len(_PROFILES)]
        headers: dict[str, str] = {}
        if cached and cached[0]:
            headers["If-None-Match"] = cached[0]
        elif cached and cached[1]:
            headers["If-Modified-Since"] = cached[1]

        try:
            try:
                resp = curl_requests.get(
                    url, headers=headers, timeout=timeout, impersonate=profile
                )
            except Exception:  # noqa: BLE001 — unknown/unsupported profile: plain GET
                resp = curl_requests.get(url, headers=headers, timeout=timeout)

            if resp.status_code == 304 and cached:
                return cached[2]

            resp.raise_for_status()
            content = resp.content

            if use_cache and content:
                _remember(
                    url,
                    resp.headers.get("ETag", ""),
                    resp.headers.get("Last-Modified", ""),
                    content,
                )
            return content

        except Exception as e:  # noqa: BLE001 — any transport failure → retry/rotate
            last_error = e
            status = getattr(e, "code", None) or getattr(
                getattr(e, "response", None), "status_code", None
            )
            # Client block (403/429): rotate fingerprint before retrying.
            if status not in (403, 429, 500, 502, 503, 504):
                if isinstance(e, curl_requests.exceptions.ConnectionError):
                    return _plain_get(url, timeout)
                logger.warning("[fastfetch] %s failed permanently: %s", url, e)
                return None
            if attempt < retries:
                time.sleep(random.uniform(0.4, 1.2) * (attempt + 1))

    logger.warning("[fastfetch] %s failed after %d attempts: %s", url, retries + 1, last_error)
    return None


def _plain_get(url: str, timeout: float) -> bytes | None:
    """Some hosts (ec.europa.eu) drop every curl_cffi TLS handshake, impersonated or
    not, yet answer a stock client."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        logger.warning("[fastfetch] %s failed permanently: %s", url, e)
        return None
