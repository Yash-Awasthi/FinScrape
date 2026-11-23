"""
Reuters scraper.
"""

from __future__ import annotations

import logging

from finscrape.models import ScrapedArticle
from finscrape.fetchers import BaseScraper

logger = logging.getLogger(__name__)


class ReutersScraper(BaseScraper):
    name = "reuters"

    SEED_URLS = [
        "https://www.reuters.com/business/",
        "https://www.reuters.com/markets/",
        "https://www.reuters.com/technology/",
    ]

    # Reuters blocks plain HTTP — use stealthy browser mode
    USE_STEALTHY = True

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
        collected = []
        seen = set()

        for seed_url in self.SEED_URLS:
            page = self.fetch_page(seed_url, stealthy=self.USE_STEALTHY)
            if not page:
                continue

            for link in page.css("a[href]"):
                href = link.attrib.get("href", "")

                if href.startswith("/"):
                    href = "https://www.reuters.com" + href

                href = href.split("?")[0]

                if href in seen:
                    continue

                if "reuters.com" not in href:
                    continue

                # Reuters article URLs typically have date patterns
                # e.g., /business/finance/some-headline-2026-04-14/
                if not any(
                    p in href
                    for p in ["/business/", "/markets/", "/technology/", "/world/"]
                ):
                    continue

                # Skip category landing pages (too short)
                parts = [p for p in href.rstrip("/").split("/") if p]
                if len(parts) < 4:
                    continue

                collected.append(href)
                seen.add(href)

            if len(collected) >= self.max_articles * 2:
                break

        return list(dict.fromkeys(collected))

    def _scrape_article(self, url: str) -> ScrapedArticle | None:
        page = self.fetch_page(url, stealthy=self.USE_STEALTHY)
        if not page:
            return None

        title = self.extract_title(page)
        text = self.extract_article_text(page)
        pub_date, age = self.extract_publish_date(page)
        tickers = self.extract_tickers_from_text(title + " " + text)

        return ScrapedArticle(
            url=url,
            title=title,
            text=text,
            source=self.name,
            published_at=pub_date,
            age_hours=age,
            raw_tickers=tickers,
        )
