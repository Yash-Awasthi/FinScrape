"""
Financial Times scraper.

FT has a hard paywall. Uses stealthy mode and focuses on
what's available from the listing pages.
"""

from __future__ import annotations

import logging

from finscrape.models import ScrapedArticle
from finscrape.fetchers import BaseScraper

logger = logging.getLogger(__name__)


class FTScraper(BaseScraper):
    name = "ft"

    SEED_URLS = [
        "https://www.ft.com/markets",
        "https://www.ft.com/companies",
        "https://www.ft.com/technology",
    ]

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
            page = self.fetch_page(seed_url, stealthy=True)
            if not page:
                continue

            for link in page.css("a[href]"):
                href = link.attrib.get("href", "")

                if href.startswith("/"):
                    href = "https://www.ft.com" + href

                href = href.split("?")[0]

                if href in seen:
                    continue

                if "ft.com" not in href:
                    continue

                # FT article URLs: /content/UUID pattern
                if "/content/" not in href:
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
