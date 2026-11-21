"""
Benzinga scraper.
"""

from __future__ import annotations

import logging

from finscrape.models import ScrapedArticle
from finscrape.scrapers import BaseScraper

logger = logging.getLogger(__name__)


class BenzingaScraper(BaseScraper):
    name = "benzinga"

    SEED_URLS = [
        "https://www.benzinga.com/news",
        "https://www.benzinga.com/markets",
        "https://www.benzinga.com/analyst-ratings",
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
            page = self.fetch_page(seed_url)
            if not page:
                continue

            for link in page.css("a[href]"):
                href = link.attrib.get("href", "")

                if href.startswith("/"):
                    href = "https://www.benzinga.com" + href

                href = href.split("?")[0]

                if href in seen:
                    continue

                if "benzinga.com" not in href:
                    continue

                # Benzinga article URLs: /news/YEAR/MM/DD/ or /analyst-ratings/ or /trading-ideas/
                if not any(
                    p in href
                    for p in ["/news/2", "/analyst-ratings/", "/trading-ideas/"]
                ):
                    continue

                # Skip category pages
                parts = [p for p in href.rstrip("/").split("/") if p]
                if len(parts) < 5:
                    continue

                collected.append(href)
                seen.add(href)

            if len(collected) >= self.max_articles * 2:
                break

        return list(dict.fromkeys(collected))

    def _scrape_article(self, url: str) -> ScrapedArticle | None:
        page = self.fetch_page(url)
        if not page:
            return None

        title = self.extract_title(page)
        text = self.extract_article_text(page)
        pub_date, age = self.extract_publish_date(page)
        tickers = self.extract_tickers_from_text(title + " " + text)

        # Benzinga uses ticker symbol links
        for sym_el in page.css('a[class*="ticker"], a[href*="/stock/"]'):
            sym = (sym_el.text or "").strip().upper()
            if 1 <= len(sym) <= 5 and sym.isalpha() and sym not in tickers:
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
