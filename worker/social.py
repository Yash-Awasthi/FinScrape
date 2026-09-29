"""Reddit posts for /api/sentiment, one RSS request per ingest run.

Reddit's JSON API answers 403 to anonymous clients, and its RSS answers a datacenter
IP once before 429s, so the worker makes a single combined multireddit fetch.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import asyncpg
import feedparser
import requests

log = logging.getLogger("worldfin.worker.social")

FEED = "https://www.reddit.com/r/stocks+wallstreetbets+investing+StockMarket/new/.rss?limit=100"
KEEP_DAYS = 14


def parse_reddit_rss(text: str) -> list[dict]:
    posts = []
    for e in feedparser.parse(text).entries:
        stamp = e.get("updated_parsed") or e.get("published_parsed")
        if not (e.get("link") and e.get("title") and stamp):
            continue
        tags = e.get("tags") or [{}]
        posts.append(
            {
                "url": e.link,
                "subreddit": tags[0].get("term", ""),
                "author": e.get("author", "").removeprefix("/u/"),
                "title": e.title,
                "published_at": datetime(*stamp[:6], tzinfo=UTC),
            }
        )
    return posts


async def store_posts(pool: asyncpg.Pool, posts: list[dict]) -> None:
    await pool.executemany(
        "INSERT INTO social_posts (url, subreddit, author, title, published_at) "
        "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (url) DO NOTHING",
        [
            (p["url"], p["subreddit"], p["author"], p["title"], p["published_at"])
            for p in posts
        ],
    )
    await pool.execute(
        "DELETE FROM social_posts WHERE published_at < now() - ($1 || ' days')::interval",
        str(KEEP_DAYS),
    )


async def refresh_social(pool: asyncpg.Pool) -> int:
    """Fetch and store; a throttled or failed fetch only skips this run."""
    try:
        resp = await asyncio.to_thread(
            requests.get,
            FEED,
            headers={"User-Agent": "Mozilla/5.0 (compatible; worldfin/1.0)"},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("reddit rss skipped: %s", exc)
        return 0
    posts = parse_reddit_rss(resp.text)
    await store_posts(pool, posts)
    log.info("reddit rss: %d posts", len(posts))
    return len(posts)
