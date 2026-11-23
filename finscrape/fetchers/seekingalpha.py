"""
Seeking Alpha scraper.

Seeking Alpha has aggressive anti-bot. Uses stealthy mode.
"""

from __future__ import annotations

import logging

from finscrape.models import ScrapedArticle
from finscrape.fetchers import BaseScraper

logger = logging.getLogger(__name__)


class SeekingAlphaScraper(BaseScraper):
    name = "seekingalpha"

    SEED_URLS = [
        "https://seekingalpha.com/market-news",
        "https://seekingalpha.com/stock-ideas",
        "https://seekingalpha.com/market-outlook",
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
                    href = "https://seekingalpha.com" + href

                href = href.split("?")[0]

                if href in seen:
                    continue

                if "seekingalpha.com" not in href:
                    continue

                # Seeking Alpha articles: /article/ or /news/
                if not any(p in href for p in ["/article/", "/news/"]):
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

        # Seeking Alpha ticker symbols in page
        for sym_el in page.css('a[href*="/symbol/"]'):
            href = sym_el.attrib.get("href", "")
            parts = href.rstrip("/").split("/")
            if parts:
                sym = parts[-1].upper()
                if 1 <= len(sym) <= 5 and sym not in tickers:
                    tickers.append(sym)

        return ScrapedArticle(
            url=url,
            title=title,
            text=text,
            source=self.name,
            published_at=pub_date,
            age_hours=age,
            raw_tickers=tickers,
        )
