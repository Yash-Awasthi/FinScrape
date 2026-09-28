"""
RSS feed scraper with full-text enrichment.

Handles Yahoo Finance RSS, CNBC RSS, and any generic financial RSS feed.
Feeds are fetched through fastfetch (browser-impersonated, conditional-GET
cached) and fetched in parallel per feed — the fastest news path.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser

from finscrape.models import ScrapedArticle
from finscrape.scrapers import BaseScraper
from finscrape.scrapers.fastfetch import fast_get

logger = logging.getLogger(__name__)


# Default financial RSS feeds
DEFAULT_FEEDS = {
    "yahoo_rss": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
    "cnbc_rss": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "marketwatch_rss": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "ft_rss": "https://www.ft.com/rss/home",
}


class RSSScraperSource(BaseScraper):
    name = "rss"

    def __init__(self, feeds: dict[str, str] | None = None, max_articles: int = 20):
        super().__init__(max_articles=max_articles)
        self.feeds = feeds or DEFAULT_FEEDS

    def _fetch_feed(self, feed_name: str, feed_url: str) -> list[ScrapedArticle]:
        """Fetch one feed (impersonated + conditional-cached) and process entries."""
        try:
            return self._fetch_feed_or_raise(feed_name, feed_url)
        except Exception as e:
            logger.warning("[%s/%s] %s", self.name, feed_name, e)
            return []

    def _fetch_feed_or_raise(self, feed_name: str, feed_url: str) -> list[ScrapedArticle]:
        raw = fast_get(feed_url)
        if not raw:
            raise RuntimeError("Feed fetch failed")
        feed = feedparser.parse(raw)
        logger.info("[%s/%s] Parsed %d entries", self.name, feed_name, len(feed.entries))

        articles = []
        for entry in feed.entries[: self.max_articles]:
            article = self._process_entry(entry, feed_name)
            if article:
                articles.append(article)
        return articles

    def scrape_news(self) -> list[ScrapedArticle]:
        # Feeds fetch in parallel — total wall time ≈ slowest feed, not their sum.
        with ThreadPoolExecutor(max_workers=min(4, len(self.feeds))) as pool:
            futures = [pool.submit(self._fetch_feed, name, url) for name, url in self.feeds.items()]
            per_feed = [f.result() for f in as_completed(futures)]
        articles = [a for feed_articles in per_feed for a in feed_articles]

        # Optionally fetch full article text for entries with URLs
        enriched = []
        for article in articles[: self.max_articles]:
            full = self._enrich_with_full_text(article)
            enriched.append(full)

        logger.info("[%s] Total articles from all feeds: %d", self.name, len(enriched))
        return enriched

    def _process_entry(self, entry: dict, feed_name: str) -> ScrapedArticle | None:
        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
        summary = entry.get("summary", "").strip()
        published = entry.get("published", "")

        if not title or not url:
            return None

        tickers = self.extract_tickers_from_text(f"{title} {summary}")

        # Compute age_hours from feedparser's parsed time struct
        age_hours: float | None = None
        pub_str: str | None = published if published else None
        parsed_time = entry.get("published_parsed")
        if parsed_time:
            import calendar
            import datetime as _dt
            epoch = calendar.timegm(parsed_time)
            dt = _dt.datetime.fromtimestamp(epoch, tz=_dt.UTC)
            age_hours = round(
                (_dt.datetime.now(_dt.UTC) - dt).total_seconds() / 3600, 1
            )

        article = ScrapedArticle(
            url=url,
            title=title,
            text=summary,
            source=f"{self.name}/{feed_name}",
            published_at=pub_str,
            age_hours=age_hours,
            raw_tickers=tickers,
        )

        if not article.is_fresh:
            return None

        return article

    def _enrich_with_full_text(self, article: ScrapedArticle) -> ScrapedArticle:
        """Fetch full article text if the RSS summary is too short.

        Two-stage enrichment: Scrapling stealth fetch → site extraction, then a
        trafilatura pass on raw HTML (best-in-class main-content extraction).
        Kills most "Insufficient content" skips.
        """
        if len(article.text) >= 300:
            return article

        page = self.fetch_page(article.url)
        if page:
            full_text = self.extract_article_text(page)
            if len(full_text) > len(article.text):
                article.text = full_text

            if not article.published_at:
                pub_date, age = self.extract_publish_date(page)
                article.published_at = pub_date
                article.age_hours = age

        if len(article.text) < 300:
            try:
                import trafilatura

                raw = fast_get(article.url)
                if raw:
                    extracted = trafilatura.extract(raw.decode("utf-8", "ignore"))
                    if extracted and len(extracted) > len(article.text):
                        article.text = extracted
            except Exception as e:  # noqa: BLE001 — enrichment is best-effort
                logger.debug("[%s] trafilatura enrichment failed: %s", self.name, e)

        return article
