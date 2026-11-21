"""
FinScrape Engine — vendored Scrapling-based scraping layer.

Uses the actual Scrapling library (v0.4.6) vendored at
finscrape.engine.scrapling for C-speed HTML parsing (lxml),
TLS fingerprint impersonation (curl_cffi), stealth browser
automation (patchright), and realistic header generation (browserforge).

Three fetch modes:

  - Fetcher:          Fast HTTP with curl_cffi TLS fingerprinting
  - StealthyFetcher:  Patchright with anti-detection (Cloudflare bypass, etc.)
  - DynamicFetcher:   Patchright for JS-heavy pages that need rendering

All return a unified `Response` object (subclass of `Selector`) with
CSS/XPath selectors so the rest of the codebase doesn't care which
fetcher was used.
"""

from finscrape.engine.scrapling import (
    AsyncFetcher,
    DynamicFetcher,
    Fetcher,
    Selector,
    StealthyFetcher,
)
from finscrape.engine.scrapling.engines.toolbelt.custom import Response

__all__ = [
    "AsyncFetcher",
    "DynamicFetcher",
    "Fetcher",
    "Response",
    "Selector",
    "StealthyFetcher",
]
