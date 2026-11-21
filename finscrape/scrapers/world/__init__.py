"""World / geopolitics scraping — thin layer over the existing RSS scraper.

Reuses RSSScraperSource verbatim for fetching/enrichment; the only differences are
(1) the feed set comes from the world registry and (2) a wider freshness window —
geopolitics stories stay relevant far longer than the 2h finance default, so we don't
want the env-driven `is_fresh` gate dropping them.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest
from urllib.parse import urlparse

import feedparser

from finscrape.models import ScrapedArticle
from finscrape.scrapers.fastfetch import fast_get
from finscrape.scrapers.rss import RSSScraperSource
from finscrape.scrapers.world.feeds import (
    FEEDS,
    SECTION_ORDER,
    feed_urls,
    section_of,
    tier_of,
)

logger = logging.getLogger(__name__)


def google_news_mirror(feed_url: str) -> str:
    """A site-scoped Google News RSS query for a feed's host, or "" for odd URLs."""
    host = urlparse(feed_url).netloc.removeprefix("www.")
    if not host or "." not in host:
        return ""
    return (
        "https://news.google.com/rss/search?"
        f"q=site%3A{host}&hl=en-US&gl=US&ceid=US%3Aen"
    )


class WorldRSSScraper(RSSScraperSource):
    name = "world"

    def __init__(self, max_articles: int = 20, max_age_hours: float = 24.0):
        super().__init__(feeds=feed_urls(), max_articles=max_articles)
        self.max_age_hours = max_age_hours
        # feed key -> (fresh entries, fetch error), filled by collect()
        self.feed_health: dict[str, tuple[int, str | None]] = {}

    def collect(self) -> list[ScrapedArticle]:
        """Every fresh entry from every feed, interleaved across feeds and sections.

        The caller caps this list to a handful of articles per cycle, so ordering is
        the whole ballgame. Two round-robins make the cap fair: sections first (so
        security, energy, shipping, macro and general news all reach the budget),
        then feeds inside each section (so one outlet cannot own its section's
        slot). Feed order inside a section advances with the UTC day.
        """
        keys = list(self.feeds)
        with ThreadPoolExecutor(max_workers=min(8, len(keys))) as pool:
            results = list(
                pool.map(lambda kv: self._fetch_one(*kv), self.feeds.items())
            )
        per_feed = [articles for articles, _ in results]
        self.feed_health = {
            key: (len(articles), error)
            for (key, _), (articles, error) in zip(self.feeds.items(), results)
        }

        by_section: dict[str, list[list[ScrapedArticle]]] = {}
        for key, articles in zip(keys, per_feed):
            by_section.setdefault(section_of(key), []).append(articles)

        day = int(time.time() // 86400)
        streams: list[list[ScrapedArticle]] = []
        for section in SECTION_ORDER:
            feeds = by_section.get(section)
            if not feeds:
                continue
            if len(feeds) > 1:
                offset = day % len(feeds)
                feeds = feeds[offset:] + feeds[:offset]
            articles = [a for row in zip_longest(*feeds) for a in row if a is not None]
            # Freshest first inside the section, so the six-article budget spends
            # its slots on today's news rather than a slow feed's oldest entry.
            # Section order is untouched: security still reaches the budget first.
            articles.sort(key=lambda a: (a.age_hours is None, a.age_hours or 0.0))
            streams.append(articles)

        out: list[ScrapedArticle] = []
        seen: set[str] = set()
        for row in zip_longest(*streams):
            for article in row:
                if article and article.url not in seen:
                    seen.add(article.url)
                    out.append(article)
        return out

    def _fetch_feed_or_raise(
        self, feed_name: str, feed_url: str
    ) -> list[ScrapedArticle]:
        """Primary RSS, then Google News' site index when the outlet blocks us.

        curl_cffi keeps most feeds open, but a few publishers still answer 403 to a
        datacentre IP or retire an RSS path without notice. Google News' RSS search
        serves the same recent headlines for that site, so a blocked feed degrades
        to headline-only analysis instead of disappearing for a whole cycle.
        """
        first_error: Exception | None = None
        try:
            articles = super()._fetch_feed_or_raise(feed_name, feed_url)
            if articles:
                return articles
        except Exception as exc:
            first_error = exc
            logger.warning("[world/%s] primary feed failed: %s", feed_name, exc)

        mirror = google_news_mirror(feed_url)
        raw = fast_get(mirror, timeout=20) if mirror else None
        entries = feedparser.parse(raw).entries[: self.max_articles] if raw else []
        mirrored = []
        for entry in entries:
            article = self._process_entry(entry, feed_name)
            if article:
                mirrored.append(article)
        if mirrored:
            logger.info(
                "[world/%s] served %d entries from the Google mirror",
                feed_name,
                len(mirrored),
            )
            return mirrored

        # Both paths failed: let the caller record a WARN instead of a silent 0.
        if first_error:
            raise first_error
        return []

    def _fetch_one(self, key: str, url: str) -> tuple[list[ScrapedArticle], str | None]:
        try:
            return self._fetch_feed_or_raise(key, url), None
        except Exception as exc:
            logger.warning("[%s/%s] %s", self.name, key, exc)
            return [], str(exc)

    def enrich(self, article: ScrapedArticle) -> ScrapedArticle:
        return self._enrich_with_full_text(article)

    def scrape_news(self) -> list[ScrapedArticle]:
        return [self.enrich(a) for a in self.collect()[: self.max_articles]]

    def _process_entry(self, entry: dict, feed_name: str) -> ScrapedArticle | None:
        """Like the base, but uses an instance freshness window (not the env gate) and
        tags the source as `world/<feed>:<tier>` so trust scoring can read the tier."""
        title = (entry.get("title") or "").strip()
        url = (entry.get("link") or "").strip()
        summary = (entry.get("summary") or "").strip()
        if not title or not url:
            return None

        age_hours: float | None = None
        parsed_time = entry.get("published_parsed")
        if parsed_time:
            dt = _dt.datetime.fromtimestamp(calendar.timegm(parsed_time), tz=_dt.UTC)
            age_hours = round(
                (_dt.datetime.now(_dt.UTC) - dt).total_seconds() / 3600, 1
            )
            if age_hours > self.max_age_hours:
                return None

        return ScrapedArticle(
            url=url,
            title=title,
            text=summary,
            source=f"{self.name}/{feed_name}:{tier_of(feed_name)}",
            published_at=entry.get("published") or None,
            age_hours=age_hours,
            raw_tickers=self.extract_tickers_from_text(f"{title} {summary}"),
        )


__all__ = ["FEEDS", "WorldRSSScraper"]
