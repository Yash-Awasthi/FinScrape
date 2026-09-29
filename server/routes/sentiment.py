"""GET /api/sentiment?ticker= — Reddit sentiment from posts the worker stored.

Reddit blocks anonymous JSON and throttles RSS after one request from a server IP,
so the worker fetches (worker/social.py) and this route only reads Postgres.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from server import db

router = APIRouter()


def _empty(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "sentiment_score": 0.0,
        "bullish_count": 0,
        "bearish_count": 0,
        "neutral_count": 0,
        "total_posts": 0,
        "bullish_pct": 0.0,
        "volume_spike": False,
        "platforms": [],
        "top_posts": [],
    }


def _aggregate(ticker: str, rows: list) -> dict:
    from finscrape.sentiment.reddit import classify_sentiment, extract_ticker_mentions

    hits = [r for r in rows if extract_ticker_mentions(r["title"], [ticker])]
    moods = [classify_sentiment(r["title"]) for r in hits]
    bull, bear = moods.count("bullish"), moods.count("bearish")
    out = _empty(ticker)
    out.update(
        sentiment_score=round((bull - bear) / len(hits), 4) if hits else 0.0,
        bullish_count=bull,
        bearish_count=bear,
        neutral_count=len(hits) - bull - bear,
        total_posts=len(hits),
        bullish_pct=round(bull / (bull + bear), 4) if bull + bear else 0.0,
        platforms=["reddit"] if hits else [],
        top_posts=[
            {
                "text": r["title"][:280],
                "author": r["author"],
                "platform": f"r/{r['subreddit']}",
                "url": r["url"],
            }
            for r in hits[:8]
        ],
    )
    return out


@router.get("/api/sentiment")
async def sentiment(ticker: str = Query(..., min_length=1, max_length=10)) -> dict:
    sym = ticker.upper().strip()
    try:
        rows = await db.pool().fetch(
            "SELECT url, subreddit, author, title FROM social_posts "
            "WHERE published_at > now() - interval '7 days' AND title ILIKE '%' || $1 || '%' "
            "ORDER BY published_at DESC",
            sym,
        )
    except Exception:  # noqa: BLE001 - a missing table or dropped pool reads as no posts
        return _empty(sym)
    return _aggregate(sym, rows)
