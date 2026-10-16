"""Base ingestor + the RawGeoEvent the pipeline consumes."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from curl_cffi import requests
from curl_cffi.requests import exceptions

from finscrape.models import ScrapedArticle

logger = logging.getLogger(__name__)

_TIMEOUT = 20
_HEADERS = {
    "User-Agent": "finscrape-worldfin/0.1 (+https://github.com/Yash-Awasthi/FinScrape)"
}

# GDELT throttles hard and inconsistently — a plain probe alternates 429/200 within
# seconds. Without a retry one throttled call cost a whole scrape cycle's worth of
# articles from the highest-volume source in the registry.
_RETRIES = 2
_BACKOFF_S = 1.5
# Only transient conditions are worth a second attempt. A 403 (unapproved appname) or
# 410 (decommissioned API version) is settled — retrying just delays the log line.
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_S = 30


def _retry_delay(resp: requests.Response, attempt: int) -> float:
    """Honour Retry-After when the server sets a sane one, else exponential backoff.

    Capped: an upstream asking us to wait ten minutes is asking for longer than the
    scrape interval, and the next cycle will retry anyway.
    """
    header = resp.headers.get("Retry-After", "")
    try:
        return min(float(header), _MAX_RETRY_AFTER_S)
    except ValueError:
        return _BACKOFF_S * (2**attempt)


@dataclass
class RawGeoEvent:
    """A pre-analysis signal from a structured API. Carries geo when the source knows
    it (USGS), else lat/lon stay None and server.geocode derives them from text."""

    title: str
    text: str
    source: str
    event_type: str = "other"  # hint; the LLM may reclassify
    lat: float | None = None
    lon: float | None = None
    published_at: str | None = None
    url: str = ""
    tickers: list[str] = field(default_factory=list)

    def to_article(self) -> ScrapedArticle:
        """Adapt to the ScrapedArticle the analyze pipeline expects (geo carried
        separately by the worker, since ScrapedArticle has no geo field)."""
        return ScrapedArticle(
            url=self.url or f"ingestor://{self.source}",
            title=self.title,
            text=self.text or self.title,
            source=self.source,
            published_at=self.published_at,
            age_hours=0.0,  # API pulls are current
            raw_tickers=list(self.tickers),
        )


class BaseIngestor(ABC):
    name: str = "base"
    base_url: str = ""

    def fetch_raw(self, url: str | None = None, params: dict | None = None) -> Any:
        """GET + JSON, retrying transient throttles. None on failure (degrade, never crash)."""
        for attempt in range(_RETRIES + 1):
            try:
                resp = requests.get(
                    url or self.base_url,
                    params=params,
                    headers=_HEADERS,
                    timeout=_TIMEOUT,
                )
                if resp.status_code in _RETRY_STATUS and attempt < _RETRIES:
                    delay = _retry_delay(resp, attempt)
                    logger.info(
                        "[ingestor/%s] %s, retrying in %.1fs",
                        self.name,
                        resp.status_code,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (exceptions.Timeout, exceptions.ConnectionError) as exc:
                if attempt < _RETRIES:
                    time.sleep(_BACKOFF_S * (attempt + 1))
                    continue
                logger.warning("[ingestor/%s] fetch failed: %s", self.name, exc)
                return None
            except (exceptions.RequestException, ValueError) as exc:
                logger.warning("[ingestor/%s] fetch failed: %s", self.name, exc)
                return None
        return None

    @abstractmethod
    def parse(self, data: Any) -> list[RawGeoEvent]:
        """Pure: raw API payload → events. Unit-tested with fixtures, no network."""
        ...

    def fetch(self) -> list[RawGeoEvent]:
        data = self.fetch_raw()
        return self.parse(data) if data is not None else []
