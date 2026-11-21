"""
Yahoo Finance scraper.
"""

from __future__ import annotations

import logging
import re

from finscrape.models import ScrapedArticle
from finscrape.scrapers import BaseScraper

logger = logging.getLogger(__name__)


class YahooScraper(BaseScraper):
    name = "yahoo"

    SEED_URLS = [
        "https://finance.yahoo.com/news/",
        "https://finance.yahoo.com/topic/stock-market-news/",
        "https://finance.yahoo.com/",
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
            page = self.fetch_page(seed_url)
            if not page:
                continue

            for link in page.css("a[href]"):
                href = link.attrib.get("href", "")

                if href.startswith("/"):
                    href = "https://finance.yahoo.com" + href

                href = href.split("?")[0]

                if href in seen:
                    continue

                if not href.endswith(".html"):
                    continue

                if "finance.yahoo.com" not in href:
                    continue

                if not any(p in href for p in ["/news/", "/video/"]):
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
        tickers = self.extract_tickers_from_text(text)

        # Also try to extract tickers from meta/script tags
        for script in page.css("script"):
            script_text = script.text or ""
            if "hashtag" in script_text:
                m = re.search(r'"hashtag":"([^"]+)"', script_text)
                if m:
                    for tag in m.group(1).split(";"):
                        if tag.startswith("$"):
                            sym = tag[1:].upper()
                            if 2 <= len(sym) <= 5 and sym not in tickers:
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
