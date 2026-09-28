"""
Base scraper class using FinScrape's vendored Scrapling engine.

All source-specific scrapers inherit from BaseScraper and implement
the `scrape_news()` method.
"""

from __future__ import annotations

import logging
import os
import re
import json
import datetime
import random
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from finscrape.models import ScrapedArticle

if TYPE_CHECKING:
    from finscrape.engine import Response

logger = logging.getLogger(__name__)

# Shared constants
MAX_WORDS = 1500
MAX_PARAGRAPHS = 25
MIN_TEXT_LENGTH = 150
MAX_AGE_HOURS = float(os.getenv("FINSCRAPE_MAX_AGE_HOURS", "2.0"))

# Retry configuration for transient fetch failures (429, 502, 503, 504, timeouts).
FETCH_MAX_RETRIES = int(os.getenv("FINSCRAPE_FETCH_RETRIES", "3"))
FETCH_BASE_DELAY = float(os.getenv("FINSCRAPE_FETCH_BASE_DELAY", "1.0"))  # seconds
FETCH_MAX_DELAY = float(os.getenv("FINSCRAPE_FETCH_MAX_DELAY", "15.0"))  # seconds
# HTTP status codes that warrant a retry (transient errors).
RETRYABLE_STATUS_HINTS = {429, 500, 502, 503, 504}
# Circuit breaker: after this many consecutive failures, the source is tripped
# and subsequent fetches fast-fail without hitting the network until reset_after_s.
CB_FAIL_THRESHOLD = int(os.getenv("FINSCRAPE_CB_FAIL_THRESHOLD", "5"))
CB_RESET_AFTER_S = float(os.getenv("FINSCRAPE_CB_RESET_AFTER_S", "60.0"))

# ── Per-source circuit breakers ────────────────────────────────────────────
_breakers: dict[str, "CircuitBreaker"] = {}


def get_breaker(name: str) -> "CircuitBreaker":
    """Get or create the circuit breaker for a named source."""
    if name not in _breakers:
        from server.circuit import CircuitBreaker
        _breakers[name] = CircuitBreaker(
            name,
            fail_threshold=CB_FAIL_THRESHOLD,
            reset_after_s=CB_RESET_AFTER_S,
        )
    return _breakers[name]


def reset_breakers() -> None:
    """Clear all circuit breakers (for tests)."""
    _breakers.clear()


class BaseScraper(ABC):
    """Base class for all news scrapers.

    Uses vendored Scrapling fetchers:
      - Fetcher:          curl_cffi with TLS fingerprinting (fast HTTP)
      - StealthyFetcher:  patchright with Cloudflare bypass
      - DynamicFetcher:   patchright for JS-heavy pages
    """

    name: str = "base"

    def __init__(self, max_articles: int = 20):
        self.max_articles = max_articles

    @abstractmethod
    def scrape_news(self) -> list[ScrapedArticle]:
        """Scrape and return a list of articles."""
        ...

    def fetch_page(
        self, url: str, stealthy: bool = False, dynamic: bool = False
    ) -> Optional[Response]:
        """Fetch a page using the appropriate Scrapling fetcher.

        Uses a per-source circuit breaker to fast-fail when a source has been
        consistently down, avoiding wasted timeout budget on every article.
        Retries on transient failures (timeouts, 429/5xx) with exponential
        backoff + jitter. Returns a Response object (extends Selector) with
        .css() and .xpath(), or None if all retries are exhausted or the
        circuit is open.
        """
        from finscrape.engine import DynamicFetcher, Fetcher, StealthyFetcher
        from server.circuit import CircuitBreaker, CircuitOpen

        breaker = get_breaker(self.name)

        # Circuit-breaker guard: if the source has tripped, fast-fail without
        # touching the network. The breaker auto-transitions to half-open after
        # CB_RESET_AFTER_S, allowing one probe request through.
        if not breaker.allow():
            logger.info("[%s] Circuit open — fast-failing fetch of %s", self.name, url)
            return None

        last_error: Optional[Exception] = None
        for attempt in range(1, FETCH_MAX_RETRIES + 1):
            try:
                if dynamic:
                    result = DynamicFetcher.fetch(url)
                elif stealthy:
                    result = StealthyFetcher.fetch(url)
                else:
                    result = Fetcher.get(url)
                breaker.record_success()
                return result
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                is_retryable = (
                    any(f" {code}" in err_str or f"{code}" in err_str[:20]
                        for code in RETRYABLE_STATUS_HINTS)
                    or "timeout" in err_str
                    or "timed out" in err_str
                    or "connection" in err_str
                    or "reset" in err_str
                )

                if not is_retryable or attempt >= FETCH_MAX_RETRIES:
                    breaker.record_failure()
                    logger.warning(
                        "[%s] Failed to fetch %s (attempt %d/%d): %s",
                        self.name, url, attempt, FETCH_MAX_RETRIES, e,
                    )
                    return None

                delay = min(FETCH_BASE_DELAY * (2 ** (attempt - 1)), FETCH_MAX_DELAY)
                delay = delay / 2 + random.uniform(0, delay / 2)
                logger.info(
                    "[%s] Transient fetch error for %s (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    self.name, url, attempt, FETCH_MAX_RETRIES, delay, e,
                )
                time.sleep(delay)

        breaker.record_failure()
        return None

    def extract_article_text(
        self, page: Response, max_paragraphs: int = MAX_PARAGRAPHS
    ) -> str:
        """Extract article text from a Response using CSS selectors."""
        article_els = page.css("article")
        if article_els:
            paragraphs = article_els[0].css("p")
        else:
            paragraphs = page.css("p")

        selected = []
        for p in paragraphs[:max_paragraphs]:
            text = p.text.strip() if p.text else ""
            if len(text) > 40:
                selected.append(text)

        text = " ".join(selected)

        # Remove junk
        for phrase in [
            "Continue reading",
            "Sign up",
            "Advertisement",
            "Read more",
            "Related stories",
        ]:
            text = text.split(phrase)[0]

        words = text.split()[:MAX_WORDS]
        return " ".join(words)

    def extract_title(self, page: Response) -> str:
        """Extract article title from meta tags or <title>."""
        # Try og:title first
        meta = page.css('meta[property="og:title"]')
        if meta:
            content = meta[0].attrib.get("content", "")
            if content:
                return re.sub(
                    r"\s*[-|]\s*(Yahoo|Bloomberg|Reuters|CNBC).*$", "", content
                ).strip()

        # Fallback to <title>
        title_tag = page.css("title")
        if title_tag:
            text = title_tag[0].text or ""
            return re.sub(
                r"\s*[-|]\s*(Yahoo|Bloomberg|Reuters|CNBC).*$", "", text
            ).strip()

        return ""

    def extract_publish_date(
        self, page: Response
    ) -> tuple[Optional[str], Optional[float]]:
        """Extract publication date and calculate age in hours."""
        pub_str = None

        # meta tag
        meta = page.css('meta[property="article:published_time"]')
        if meta:
            pub_str = meta[0].attrib.get("content")

        # JSON-LD fallback
        if not pub_str:
            for script in page.css('script[type="application/ld+json"]'):
                try:
                    text = script.text
                    if not text:
                        continue
                    data = json.loads(text)
                    if isinstance(data, list):
                        data = data[0]
                    if isinstance(data, dict):
                        pub_str = data.get("datePublished")
                    if pub_str:
                        break
                except Exception:
                    pass

        if not pub_str:
            return None, None

        try:
            dt = datetime.datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            age_hours = (
                datetime.datetime.now(datetime.timezone.utc) - dt
            ).total_seconds() / 3600
            return pub_str, round(age_hours, 1)
        except Exception:
            return pub_str, None

    @staticmethod
    def extract_tickers_from_text(text: str) -> list[str]:
        """Extract ticker symbols from text using regex + company name mapping."""
        from finscrape.analysis.ticker_map import resolve_company_tickers
        from finscrape.analysis.validator import clean_tickers

        tickers = set()

        # (TICKER) pattern — e.g. (AAPL)
        tickers.update(re.findall(r"\(([A-Z]{1,5})\)", text))
        # $TICKER pattern — e.g. $AAPL
        tickers.update(re.findall(r"\$([A-Z]{1,5})\b", text))
        # Exchange-prefixed — e.g. NYSE: XYZ. Bare capitals are left out: in news
        # copy they are acronyms (IE, KBRA, NATO) far more often than symbols.
        tickers.update(re.findall(r"\b(?:NYSE|NASDAQ|Nasdaq|AMEX)\s*:\s*([A-Z]{1,5})\b", text))
        # Futures — e.g. ES=F
        tickers.update(re.findall(r"\b([A-Z]{1,2}=F)\b", text))
        # Indexes — e.g. ^GSPC
        tickers.update(re.findall(r"(\^[A-Z]{2,5})\b", text))

        # Company name → ticker mapping (word-boundary match, the one map)
        tickers.update(resolve_company_tickers(text))

        # Drop stopwords, except real tickers written as explicit $TICK/(TICK) shorthand
        return [t for t in clean_tickers(list(tickers), text=text) if 1 <= len(t) <= 5]

    def close(self):
        """No-op — Scrapling fetchers are class-level, no instance cleanup needed."""
        pass
