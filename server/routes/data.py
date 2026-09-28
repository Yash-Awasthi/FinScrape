"""Auxiliary data routes for Phase 6 panels: RSS proxy, ticker rollup, suggestions.

Network calls (RSS) run in a threadpool with a short in-memory cache so they don't
block the event loop or hammer upstreams. The RSS proxy is SSRF-guarded: it only
fetches URLs from the world feed registry (no arbitrary user URLs).
"""

from __future__ import annotations

import asyncio

import requests
from fastapi import APIRouter, HTTPException, Query

from finscrape.scrapers.world.feeds import FEEDS, get_feed
from server import cache, db
from server.circuit import CircuitBreaker
from server.ssrf import assert_public_url

router = APIRouter()

_HEADERS = {"User-Agent": "finscrape-worldfin/0.1"}
_TIMEOUT = 15

# Per-upstream breakers: a dead host fails fast instead of burning a thread + 15s timeout
# on every request until its TTL cache entry would refill.
_rss_cb = CircuitBreaker("rss")


# --- RSS proxy (allowlisted by feed key — SSRF guard) ---


def _fetch_rss(url: str, limit: int) -> list[dict]:
    import feedparser

    # SSRF guard: validate before fetch, then re-validate every redirect hop so a
    # registry host that 302s to a private address is still rejected. We fetch the
    # bytes ourselves (requests) instead of letting feedparser open the socket.
    assert_public_url(url)
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, stream=False)
    for hop in (*resp.history, resp):
        assert_public_url(hop.url)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries[:limit]:
        items.append(
            {
                "title": (e.get("title") or "").strip(),
                "link": (e.get("link") or "").strip(),
                "published": e.get("published", ""),
            }
        )
    return items


@router.get("/api/rss-proxy")
async def rss_proxy(
    feed: str = Query(...), limit: int = Query(20, ge=1, le=50)
) -> dict:
    f = get_feed(feed)
    if f is None:
        # only registry feeds are proxied — blocks arbitrary-URL SSRF
        raise HTTPException(status_code=400, detail="unknown feed key")
    try:
        items = await asyncio.to_thread(
            lambda: cache.get_or_set(
                f"rss:{feed}:{limit}",
                cache.MEDIUM,
                lambda: _rss_cb.call(lambda: _fetch_rss(f.url, limit)),
            )
        )
    except Exception:  # noqa: BLE001 — feed failures degrade to empty
        items = []
    return {"feed": feed, "name": f.name, "tier": f.tier, "items": items}


@router.get("/api/feeds")
async def feeds() -> dict:
    """The world feed registry (for the WorldNews panel's source picker)."""
    return {
        "feeds": [
            {"key": f.key, "name": f.name, "tier": f.tier, "region": f.region}
            for f in FEEDS
        ]
    }


# --- markets (ticker frequency from stored events; live quotes deferred to Phase 8) ---


@router.get("/api/markets")
async def markets(limit: int = Query(20, ge=1, le=100)) -> dict:
    """Most-mentioned tickers across recent events. Live price quotes are deferred
    (yfinance hot-path cost, RISKS R1) — this is the cheap event-derived rollup."""
    rows = await db.pool().fetch(
        """
        SELECT t.ticker, COUNT(*) AS mentions,
               AVG(signal_score)::float AS avg_score
        FROM events e, jsonb_array_elements_text(e.tickers) AS t(ticker)
        WHERE e.timestamp >= now() - interval '7 days'
        GROUP BY t.ticker ORDER BY mentions DESC LIMIT $1
        """,
        limit,
    )
    return {
        "tickers": [
            {
                "ticker": r["ticker"],
                "mentions": r["mentions"],
                "avg_score": round(r["avg_score"], 2),
            }
            for r in rows
        ]
    }


# --- suggestions (what to look at next, derived from event flow + trust) ---

_SUGGESTIONS_SQL = """
WITH recent AS (
    SELECT e.id, e.subject, e.tickers, e.signal_score, e.confidence,
           e.verdict, e.sector_impact, e.actionability, e.timestamp
    FROM events e
    WHERE e.timestamp >= now() - interval '7 days'
),
ticker_stats AS (
    SELECT t.ticker,
           COUNT(*)::float AS mentions,
           -- velocity: mentions in the last 12h vs the previous 36h (surge = accelerating coverage)
           COUNT(*) FILTER (WHERE r.timestamp >= now() - interval '12 hours')::float AS recent_mentions,
           GREATEST(COUNT(*) FILTER (WHERE r.timestamp < now() - interval '12 hours'
                                          AND r.timestamp >= now() - interval '48 hours')::float, 1) AS baseline_mentions,
           AVG(r.confidence)::float AS avg_confidence,
           AVG(r.signal_score)::float AS avg_score,
           MAX(r.timestamp) AS last_seen,
           SUM(CASE WHEN r.verdict IN ('INVEST', 'PULL_OUT') THEN 1 ELSE 0 END)::float AS directional,
           -- The newest event per ticker. These read `recent`, so they belong here:
           -- the outer query's alias is ticker_stats, which has no event columns.
           (ARRAY_AGG(r.subject ORDER BY r.timestamp DESC))[1] AS latest_subject,
           (ARRAY_AGG(r.verdict ORDER BY r.timestamp DESC))[1] AS latest_verdict,
           (ARRAY_AGG(r.sector_impact ORDER BY r.timestamp DESC))[1] AS sector
    FROM recent r, jsonb_array_elements_text(r.tickers) AS t(ticker)
    GROUP BY t.ticker
),
source_accuracy AS (
    SELECT s.ticker, AVG(s.hit_rate)::float AS trust
    FROM (
        SELECT jsonb_array_elements_text(e.tickers) AS ticker,
               CASE WHEN e.verdict IN ('INVEST', 'PULL_OUT') THEN 1.0 ELSE 0.5 END AS hit_rate
        FROM events e
        WHERE e.timestamp >= now() - interval '30 days'
              AND e.verdict IN ('INVEST', 'PULL_OUT')
    ) s
    GROUP BY s.ticker
)
SELECT r.ticker, r.mentions, r.avg_confidence, r.avg_score, r.last_seen,
       COALESCE(sa.trust, 0.5) AS trust,
       (r.mentions * r.avg_confidence * (0.5 + ABS(r.avg_score) / 10.0)
        * (0.5 + COALESCE(sa.trust, 0.5))
        * (1 + LEAST(2.0, r.recent_mentions / r.baseline_mentions)))::float AS suggestion_score,
       r.recent_mentions / r.baseline_mentions::float AS momentum,
       r.latest_subject, r.latest_verdict, r.sector
FROM ticker_stats r
LEFT JOIN source_accuracy sa ON sa.ticker = r.ticker
ORDER BY suggestion_score DESC
LIMIT $1
"""


@router.get("/api/suggestions")
async def suggestions(limit: int = Query(10, ge=1, le=50)) -> dict:
    """Rank tickers to look at next: mention volume × confidence × score magnitude
    × realized directional trust. Pure event-derived — no external calls."""
    rows = await db.pool().fetch(_SUGGESTIONS_SQL, limit)
    return {
        "suggestions": [
            {
                "ticker": r["ticker"],
                "score": round(r["suggestion_score"], 3),
                "momentum": round(r["momentum"], 2)
                if r["momentum"] is not None
                else None,
                "mentions": int(r["mentions"]),
                "avg_score": round(r["avg_score"], 2),
                "avg_confidence": round(r["avg_confidence"], 2),
                "trust": round(r["trust"], 2),
                "latest_subject": r["latest_subject"],
                "latest_verdict": r["latest_verdict"],
                "sector": r["sector"],
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            }
            for r in rows
        ]
    }


# --- sector heat (production parity for /api/sectors) ---

from finscrape.analysis.sectors import normalize as _normalize_sector


@router.get("/api/sectors")
async def sectors() -> dict:
    """Sector heat: Postgres GROUP BY on sector_impact, plus an NLP fallback for
    unlabeled events so the panel never shows an empty half. Same contract as the
    local route: {sector, event_count, avg_score, bull_bear_ratio, top_tickers, last_event}."""
    pool = db.pool()
    labeled = await pool.fetch(
        """
        SELECT e.sector_impact AS sector, COUNT(*)::int AS event_count,
               AVG(e.signal_score)::float AS avg_score,
               COUNT(*) FILTER (WHERE e.verdict IN ('INVEST', 'OBSERVE'))::float AS bulls,
               COUNT(*) FILTER (WHERE e.verdict IN ('PULL_OUT', 'CAUTIOUS'))::float AS bears
        FROM events e
        WHERE e.sector_impact <> ''
        GROUP BY e.sector_impact
        """
    )
    last_rows = await pool.fetch(
        """
        SELECT DISTINCT ON (e.sector_impact) e.sector_impact AS sector,
               e.subject, e.created_at
        FROM events e
        WHERE e.sector_impact <> ''
        ORDER BY e.sector_impact, e.id DESC
        """
    )
    last_by_sector = {r["sector"]: r for r in last_rows}
    ticker_rows = await pool.fetch(
        """
        SELECT e.sector_impact AS sector, t.ticker, COUNT(*)::int AS n
        FROM events e
        CROSS JOIN LATERAL jsonb_array_elements_text(e.tickers) AS t(ticker)
        WHERE e.sector_impact <> ''
        GROUP BY e.sector_impact, t.ticker
        ORDER BY e.sector_impact, n DESC
        """
    )
    # Counts are summed per NORMALIZED sector: two raw labels that alias to the same
    # sector ("finance"/"financials") contribute to one ranking, not two.
    ticker_counts: dict[str, dict[str, int]] = {}
    for r in ticker_rows:
        for sec in _normalize_sector(r["sector"]):
            counts = ticker_counts.setdefault(sec, {})
            counts[r["ticker"]] = counts.get(r["ticker"], 0) + int(r["n"])

    # Unlabeled events → NLP sector from subject (keyword-only, no spaCy model load).
    from finscrape.analysis.nlp import FinancialNLP

    nlp = FinancialNLP()
    unlabeled = await pool.fetch(
        """
        SELECT subject, tickers, signal_score, verdict, created_at
        FROM events
        WHERE sector_impact IS NULL OR sector_impact = ''
        ORDER BY id DESC LIMIT 500
        """
    )
    fallback: dict[str, dict] = {}
    for r in unlabeled:
        sector = nlp._detect_sector(r["subject"] or "", r["tickers"] or [])
        parts = _normalize_sector(sector)
        if not parts:
            continue
        for sec in parts:
            a = fallback.setdefault(
                sec,
                {
                    "event_count": 0,
                    "scores": [],
                    "bulls": 0,
                    "bears": 0,
                    "last_event": None,
                },
            )
            a["event_count"] += 1
            a["scores"].append(float(r["signal_score"] or 0))
            if r["verdict"] in ("INVEST", "OBSERVE"):
                a["bulls"] += 1
            elif r["verdict"] in ("PULL_OUT", "CAUTIOUS"):
                a["bears"] += 1
            if a["last_event"] is None:
                a["last_event"] = {
                    "subject": r["subject"],
                    "created_at": r["created_at"],
                }

    # One accumulator per normalized sector. Labeled and NLP-fallback events both add
    # into it, so aliased labels merge instead of overwriting and every rendered field
    # (score, bull/bear, tickers, last event) reflects the full set.
    acc: dict[str, dict] = {}

    def _bucket(sec: str) -> dict:
        return acc.setdefault(
            sec,
            {
                "event_count": 0,
                "score_sum": 0.0,
                "bulls": 0,
                "bears": 0,
                "last_event": None,
            },
        )

    def _keep_latest(bucket: dict, subject: str, created_at) -> None:
        current = bucket["last_event"]
        if current is None or (
            created_at is not None
            and current["created_at"] is not None
            and created_at > current["created_at"]
        ):
            bucket["last_event"] = {"subject": subject, "created_at": created_at}

    for r in labeled:
        count = int(r["event_count"])
        for sec in _normalize_sector(r["sector"]):
            b = _bucket(sec)
            b["event_count"] += count
            b["score_sum"] += float(r["avg_score"] or 0.0) * count
            b["bulls"] += int(r["bulls"])
            b["bears"] += int(r["bears"])
            lr = last_by_sector.get(r["sector"])
            if lr is not None:
                _keep_latest(b, lr["subject"], lr["created_at"])

    for sec, a in fallback.items():
        b = _bucket(sec)
        b["event_count"] += a["event_count"]
        b["score_sum"] += sum(a["scores"])
        b["bulls"] += a["bulls"]
        b["bears"] += a["bears"]
        if a["last_event"]:
            _keep_latest(b, a["last_event"]["subject"], a["last_event"]["created_at"])

    merged = {
        sec: {
            "sector": sec,
            "event_count": b["event_count"],
            "avg_score": round(b["score_sum"] / b["event_count"], 2)
            if b["event_count"]
            else 0.0,
            "bull_bear_ratio": round((b["bulls"] + 1) / (b["bears"] + 1), 2),
            "top_tickers": [
                t
                for t, _ in sorted(
                    ticker_counts.get(sec, {}).items(), key=lambda kv: (-kv[1], kv[0])
                )[:5]
            ],
            "last_event": b["last_event"],
        }
        for sec, b in acc.items()
    }
    out = sorted(merged.values(), key=lambda s: s["event_count"], reverse=True)
    return {"sectors": out}


@router.get("/api/storylines")
async def storylines(limit: int = Query(10, ge=1, le=50)) -> dict:
    """Storylines (production parity): greedy embedding clusters of recent events.
    Same contract as the local route; Ollama down → singleton clusters."""
    from finscrape.analysis.clusters import build_storylines

    rows = await db.pool().fetch(
        """
        SELECT id, subject, tickers, sources, signal_score, created_at
        FROM events ORDER BY id DESC LIMIT 200
        """
    )  # newest 200: the feed's own universe (/api/events limit) — duplicates
    # beyond that window can never render, so don't spend Ollama calls on them.
    events = [
        {
            "id": r["id"],
            "subject": r["subject"],
            "tickers": r["tickers"] or [],
            "sources": r["sources"] or [],
            "signal_score": r["signal_score"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return {"storylines": build_storylines(events)[:limit]}
