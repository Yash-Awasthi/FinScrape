"""Reddit posts arrive by RSS in the worker and /api/sentiment reads them from Postgres.

Reddit answers the first RSS request from a datacenter IP and 429s the next, so one
combined fetch per ingest run replaces per-request scraping from the API.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("asyncpg")

from tests.server import fresh_pool, pg_reachable

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><author><name>/u/alice</name></author><category term="stocks" label="r/stocks"/>
<id>t3_a</id><link href="https://www.reddit.com/r/stocks/comments/a/x/"/>
<updated>2026-09-28T10:00:00+00:00</updated><title>$AAPL breakout, loading calls</title></entry>
<entry><author><name>/u/bob</name></author><category term="investing" label="r/investing"/>
<id>t3_b</id><link href="https://www.reddit.com/r/investing/comments/b/y/"/>
<updated>2026-09-28T11:00:00+00:00</updated><title>AAPL looks overvalued, selling</title></entry>
</feed>"""


def test_parse_reddit_rss():
    from worker.social import parse_reddit_rss

    posts = parse_reddit_rss(RSS)
    assert [(p["subreddit"], p["author"]) for p in posts] == [
        ("stocks", "alice"),
        ("investing", "bob"),
    ]
    assert posts[0]["url"] == "https://www.reddit.com/r/stocks/comments/a/x/"
    assert posts[0]["published_at"].year == 2026


@pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)
def test_sentiment_reads_stored_posts(monkeypatch):
    from datetime import UTC, datetime

    from server import db
    from server.routes.sentiment import sentiment
    from worker.social import parse_reddit_rss, store_posts

    async def body():
        pool = await fresh_pool("social_posts")
        posts = parse_reddit_rss(RSS)
        for p in posts:
            p["published_at"] = datetime.now(UTC)
        await store_posts(pool, posts)
        await store_posts(pool, posts)  # a repeat fetch must not double count
        got = await sentiment(ticker="aapl")
        assert (got["total_posts"], got["bullish_count"], got["bearish_count"]) == (
            2,
            1,
            1,
        )
        assert got["platforms"] == ["reddit"]
        assert (await sentiment(ticker="MSFT"))["total_posts"] == 0
        await db.disconnect()

    asyncio.run(body())
