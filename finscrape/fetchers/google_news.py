"""
Google News Business topic scraper using Scrapling's Fetcher.

Scrapes the Google News Business section directly for headlines
and follows links to original articles for full text.
"""

from __future__ import annotations

import logging

from finscrape.models import ScrapedArticle
from finscrape.fetchers import BaseScraper

logger = logging.getLogger(__name__)

# Google News Business topic — English US
TOPIC_URL = (
    "https://news.google.com/topics/"
    "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB"
    "?hl=en-US&gl=US&ceid=US:en"
)


class GoogleNewsScraper(BaseScraper):
    name = "google_news"

    def scrape_news(self) -> list[ScrapedArticle]:
        urls = self._collect_article_urls()
        logger.info("[%s] Collected %d article URLs", self.name, len(urls))

        articles = []
        for url in urls[: self.max_articles]:
            article = self._scrape_article(url)
            if article and article.has_content and article.is_fresh:
                articles.append(article)

        logger.info("[%s] Scraped %d valid articles", self.name, len(articles))
        return articles

    def _collect_article_urls(self) -> list[str]:
        """Fetch the Google News topic page and extract article links."""
        page = self.fetch_page(TOPIC_URL, stealthy=True)
        if not page:
            logger.warning("[%s] Failed to fetch Google News topic page", self.name)
            return []

        collected = []
        seen = set()

        for link in page.css("a[href]"):
            href = link.attrib.get("href", "")

            # Google News uses relative ./articles/... links
            if href.startswith("./articles/"):
                href = "https://news.google.com/" + href[2:]

            # Skip non-article links
            if (
                "news.google.com/articles/" not in href
                and "news.google.com/read/" not in href
            ):
                continue

            if href in seen:
                continue
            seen.add(href)
            collected.append(href)

            if len(collected) >= self.max_articles * 3:
                break

        return collected

    def _resolve_google_url(self, gnews_url: str) -> str | None:
        """Follow a Google News redirect to the original article URL."""
        try:
            page = self.fetch_page(gnews_url)
            if not page:
                return None
            # Google News redirects — check for meta refresh or canonical
            canonical = page.css('link[rel="canonical"]')
            if canonical:
                return canonical[0].attrib.get("href")
            # Try og:url
            og = page.css('meta[property="og:url"]')
            if og:
                return og[0].attrib.get("content")
            return None
        except Exception as e:
            logger.debug("[%s] Failed to resolve %s: %s", self.name, gnews_url, e)
            return None

    def _scrape_article(self, gnews_url: str) -> ScrapedArticle | None:
        """Resolve a Google News URL and scrape the original article."""
        # First, follow the Google News redirect to get the real URL
        real_url = self._resolve_google_url(gnews_url)
        if not real_url:
            # If resolution fails, try scraping the gnews URL directly
            real_url = gnews_url

        page = self.fetch_page(real_url)
        if not page:
            return None

        title = self.extract_title(page)
        if not title:
            return None

        text = self.extract_article_text(page)
        pub_date, age_hours = self.extract_publish_date(page)
        tickers = self.extract_tickers_from_text(title + " " + text)

        return ScrapedArticle(
            url=real_url,
            title=title,
            text=text,
            source=self.name,
            published_at=pub_date,
            age_hours=age_hours,
            raw_tickers=tickers,
        )
