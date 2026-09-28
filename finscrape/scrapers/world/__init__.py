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
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest

from finscrape.models import ScrapedArticle
from finscrape.scrapers.rss import RSSScraperSource
from finscrape.scrapers.world.feeds import FEEDS, feed_urls, tier_of

logger = logging.getLogger(__name__)


class WorldRSSScraper(RSSScraperSource):
    name = "world"

    def __init__(self, max_articles: int = 20, max_age_hours: float = 24.0):
        super().__init__(feeds=feed_urls(), max_articles=max_articles)
        self.max_age_hours = max_age_hours
        # feed key -> (fresh entries, fetch error), filled by collect()
        self.feed_health: dict[str, tuple[int, str | None]] = {}

    def collect(self) -> list[ScrapedArticle]:
        """Every fresh entry from every feed, un-enriched, interleaved across feeds.

        Interleaving matters because callers cap the list: concatenated, the first
        feeds to answer filled the whole budget and the rest never contributed.
        """
        with ThreadPoolExecutor(max_workers=min(8, len(self.feeds))) as pool:
            results = list(
                pool.map(lambda kv: self._fetch_one(*kv), self.feeds.items())
            )
        per_feed = [articles for articles, _ in results]
        self.feed_health = {
            key: (len(articles), error)
            for key, (articles, error) in zip(self.feeds, results)
        }
        out: list[ScrapedArticle] = []
        seen: set[str] = set()
        for row in zip_longest(*per_feed):
            for article in row:
                if article and article.url not in seen:
                    seen.add(article.url)
                    out.append(article)
        return out

    def _fetch_one(self, key: str, url: str) -> tuple[list[ScrapedArticle], str | None]:
        try:
            return self._fetch_feed_or_raise(key, url), None
        except Exception as exc:  # noqa: BLE001 - one broken feed must not sink the others
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
