"""
FinScrape configuration — all tunable parameters in one place.
Loads from environment variables with sensible defaults.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    # AI
    openrouter_api_key: str = ""
    openai_base_url: str = ""
    openai_api_key: str = "proxy"
    ai_model: str = "auto"
    ai_temperature: float = 0.1
    ai_max_tokens: int = 3000
    ai_timeout: int = 60
    ai_max_retries: int = 1
    ai_retry_base_delay: float = 2.0

    # Scraping
    max_articles_per_source: int = 30
    max_article_age_hours: float = 2.0
    max_paragraphs: int = 25
    max_words: int = 700
    min_text_length: int = 150

    # Verdict thresholds
    invest_threshold: int = 3
    observe_threshold: int = 1
    cautious_threshold: int = -1

    # Deduplication
    dedup_similarity: float = 0.85
    dedup_ticker_overlap: float = 0.5
    divergence_penalty: float = 0.15

    # Storage
    data_dir: str = ""

    # RSS feeds (comma-separated override)
    rss_feeds: str = ""

    @classmethod
    def from_env(cls) -> Config:
        """Load config from environment variables."""
        return cls(
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", "proxy"),
            ai_model=os.getenv("FINSCRAPE_MODEL", "auto"),
            ai_temperature=float(os.getenv("FINSCRAPE_AI_TEMP", "0.1")),
            ai_max_tokens=int(os.getenv("FINSCRAPE_AI_MAX_TOKENS", "3000")),
            ai_timeout=int(os.getenv("FINSCRAPE_AI_TIMEOUT", "60")),
            ai_max_retries=int(os.getenv("FINSCRAPE_AI_MAX_RETRIES", "1")),
            ai_retry_base_delay=float(os.getenv("FINSCRAPE_AI_RETRY_DELAY", "2.0")),
            max_articles_per_source=int(os.getenv("FINSCRAPE_MAX_ARTICLES", "30")),
            max_article_age_hours=float(os.getenv("FINSCRAPE_MAX_AGE_HOURS", "2.0")),
            max_paragraphs=int(os.getenv("FINSCRAPE_MAX_PARAGRAPHS", "25")),
            max_words=int(os.getenv("FINSCRAPE_MAX_WORDS", "700")),
            min_text_length=int(os.getenv("FINSCRAPE_MIN_TEXT_LENGTH", "150")),
            invest_threshold=int(os.getenv("FINSCRAPE_INVEST_THRESHOLD", "3")),
            observe_threshold=int(os.getenv("FINSCRAPE_OBSERVE_THRESHOLD", "1")),
            cautious_threshold=int(os.getenv("FINSCRAPE_CAUTIOUS_THRESHOLD", "-1")),
            dedup_similarity=float(os.getenv("FINSCRAPE_DEDUP_SIMILARITY", "0.85")),
            dedup_ticker_overlap=float(os.getenv("FINSCRAPE_DEDUP_OVERLAP", "0.5")),
            divergence_penalty=float(os.getenv("FINSCRAPE_DIVERGENCE_PENALTY", "0.15")),
            data_dir=os.getenv("FINSCRAPE_DATA_DIR", ""),
            rss_feeds=os.getenv("FINSCRAPE_RSS_FEEDS", ""),
        )

# Global singleton
config = Config.from_env()
