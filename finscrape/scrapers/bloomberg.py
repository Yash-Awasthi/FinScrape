"""
Bloomberg scraper using StealthFetcher for anti-bot bypass.

Bloomberg has strong anti-bot protection. We use StealthFetcher
which handles Cloudflare and other WAFs via Playwright stealth.
"""

from __future__ import annotations

import logging

from finscrape.models import ScrapedArticle
from finscrape.scrapers import BaseScraper

logger = logging.getLogger(__name__)


class BloombergScraper(BaseScraper):
    name = "bloomberg"

    SEED_URLS = [
        "https://www.bloomberg.com/markets",
        "https://www.bloomberg.com/technology",
        "https://www.bloomberg.com/economics",
    ]

    def scrape_news(self) -> list[ScrapedArticle]:
        urls = self._collect_article_urls()
        logger.info("[%s] Collected %d article URLs", self.name, len(urls))

        articles = []
        for url in urls[:self.max_articles]:
            article = self._scrape_article(url)
            if article and article.has_content and article.is_fresh:
                articles.append(article)

        logger.info("[%s] Scraped %d valid articles", self.name, len(articles))
        return articles

    def _collect_article_urls(self) -> list[str]:
        collected = []
        seen = set()

        for seed_url in self.SEED_URLS:
            page = self.fetch_page(seed_url, stealthy=True)
            if not page:
                continue

            for link in page.css("a[href]"):
                href = link.attrib.get("href", "")

                if href.startswith("/"):
                    href = "https://www.bloomberg.com" + href

                href = href.split("?")[0]

                if href in seen:
                    continue

                if "bloomberg.com" not in href:
                    continue

                # Bloomberg article URLs contain /news/ or /articles/
                # Skip /opinion/ — these are editorial, not news
                if "/opinion/" in href:
                    continue
                if not any(p in href for p in ["/news/", "/articles/"]):
                    continue

                collected.append(href)
                seen.add(href)

            if len(collected) >= self.max_articles * 2:
                break

        return list(dict.fromkeys(collected))

    def _scrape_article(self, url: str) -> ScrapedArticle | None:
        page = self.fetch_page(url, stealthy=True)
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
