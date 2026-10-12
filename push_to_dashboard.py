"""
FinScrape -> Dashboard Push Script

Scrapes news from all sources and pushes them to the dashboard API.

Scoring uses the same AI + heuristic fusion that pipeline.py uses:
  1. Heuristic runs first (always — cheap, never fails)
  2. AI analysis via Ollama/Qwen or any OpenAI-compatible endpoint
  3. Fusion: divergence penalty, source credibility, recency decay
  4. Graceful fallback to heuristic-only if AI is unavailable

Run with --no-ai to force heuristic-only mode.
Run with --concurrency 4 to parallelise AI calls (3-4x speedup).
"""

import sys
import os
import logging
import json
import argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.WARNING)

from finscrape.models import Verdict
from finscrape.scrapers.bloomberg    import BloombergScraper
from finscrape.scrapers.reuters      import ReutersScraper
from finscrape.scrapers.marketwatch  import MarketWatchScraper
from finscrape.scrapers.investingcom import InvestingComScraper
from finscrape.scrapers.seekingalpha import SeekingAlphaScraper
from finscrape.scrapers.ft           import FTScraper
from finscrape.scrapers.yahoo        import YahooScraper
from finscrape.scrapers.cnbc         import CNBCScraper
from finscrape.scrapers.benzinga     import BenzingaScraper
from finscrape.scrapers.google_news  import GoogleNewsScraper

from finscrape.analysis.validator import (
    calculate_heuristic_score,
    check_divergence,
    clean_tickers,
    apply_source_credibility,
    apply_recency_decay,
)

import requests

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_URL = os.getenv("FINSCRAPE_DASHBOARD_URL", "http://localhost:8787")
DEFAULT_KEY = os.getenv("FINSCRAPE_API_KEY", "local-dev-key")

SOURCES = [
    ("bloomberg",   BloombergScraper),
    ("reuters",     ReutersScraper),
    ("marketwatch", MarketWatchScraper),
    ("investingcom", InvestingComScraper),
    ("seekingalpha", SeekingAlphaScraper),
    ("ft",          FTScraper),
    ("yahoo",       YahooScraper),
    ("cnbc",        CNBCScraper),
    ("benzinga",    BenzingaScraper),
    ("google_news", GoogleNewsScraper),
]

# ---------------------------------------------------------------------------
# Helpers (kept from original — still used in heuristic fallback)
# ---------------------------------------------------------------------------

def heuristic_verdict(score: int) -> str:
    return Verdict.from_score(score).value


def guess_direction(title: str, text: str) -> str:
    combined = (title + " " + text).lower()
    pos = ["rally", "surge", "jump", "climb", "gain", "rise", "higher", "beat",
           "record", "upgrade", "buy", "bullish", "soar", "boom", "positive",
           "growth", "profit"]
    neg = ["fall", "drop", "slip", "decline", "crash", "plunge", "loss", "cut",
           "downgrade", "sell", "bearish", "slump", "negative", "fear", "risk",
           "warn", "crisis", "block"]
    pos_count = sum(1 for w in pos if w in combined)
    neg_count = sum(1 for w in neg if w in combined)
    if pos_count > neg_count: return "positive"
    if neg_count > pos_count: return "negative"
    return "neutral"


def guess_event_type(title: str, text: str) -> str:
    combined = (title + " " + text).lower()
    if any(w in combined for w in ["earnings", "revenue", "profit", "quarterly"]):
        return "earnings"
    if any(w in combined for w in ["merger", "acqui", "deal", "buyout"]):
        return "merger_acquisition"
    if any(w in combined for w in ["upgrade", "downgrade", "target", "rating"]):
        return "analyst_upgrade"
    if any(w in combined for w in ["launch", "product", "announce"]):
        return "product_launch"
    return "market_movement"


# ---------------------------------------------------------------------------
# AI lazy-import helper
# ---------------------------------------------------------------------------

def _try_import_ai():
    """
    Lazy-import AI modules so --no-ai mode works even if the AI stack is
    misconfigured (e.g. missing OPENAI_BASE_URL).
    Returns (call_ai, SYSTEM_PROMPT, ANALYSIS_PROMPT) or (None, None, None).
    """
    try:
        from finscrape.analysis.ai_client import call_ai
        from finscrape.analysis.prompts   import SYSTEM_PROMPT, ANALYSIS_PROMPT
        return call_ai, SYSTEM_PROMPT, ANALYSIS_PROMPT
    except Exception as e:
        logging.warning("Could not import AI modules: %s — AI disabled.", e)
        return None, None, None


# ---------------------------------------------------------------------------
# Core: article → event dict
# ---------------------------------------------------------------------------

def article_to_event(article, source_name: str, use_ai: bool = True) -> dict | None:
    """
    Convert a scraped article to a dashboard event dict.

    Scoring mirrors pipeline.py:_analyze_article exactly:
      - final_score = clamp(ai.signal_score, -5, 5), clamped to [-2, 2] on divergence
      - divergence penalty also applied to confidence
      - source credibility and recency decay applied after divergence
    """
    title     = article.title or ""
    text      = article.text  or ""
    full_text = title + " " + text

    # 1. Heuristic always runs — cheap, deterministic, never raises
    h_sentiment, h_impact = calculate_heuristic_score(
        full_text, guess_event_type(title, text)
    )

    # 2. AI analysis
    ai_result = None
    if use_ai:
        call_ai, SYSTEM_PROMPT, ANALYSIS_PROMPT = _try_import_ai()
        if call_ai is not None:
            try:
                # Mirrors pipeline.py:_analyze_with_single_ai exactly —
                # uses .replace() with {{title}} and {{article_text}} placeholders
                prompt = (
                    ANALYSIS_PROMPT
                    .replace("{{title}}", title)
                    .replace("{{article_text}}", text[:3000])  # truncate long articles
                )
                ai_result = call_ai(prompt, SYSTEM_PROMPT)
            except Exception as e:
                logging.warning(
                    "AI call failed for '%s': %s — falling back to heuristic",
                    title[:60], e
                )

    # 3. Fusion or fallback
    if ai_result and ai_result.get("relevant"):
        # ── AI + heuristic fusion (mirrors pipeline.py:_analyze_article) ──
        base_score = ai_result.get("signal_score", 0)
        direction  = ai_result.get("impact_direction", "neutral")
        event_type = ai_result.get("event_type", "market_movement")
        confidence = ai_result.get("confidence", 0.5)
        reasoning  = ai_result.get("reasoning", "")
        ai_tickers = ai_result.get("tickers", []) or []
        magnitude  = ai_result.get("magnitude", "medium")
        sector     = ai_result.get("sector_impact", "")

        final_score = max(-5, min(5, base_score))

        # Divergence check: AI direction vs heuristic sentiment
        divergence = check_divergence(direction, h_sentiment)
        if divergence:
            final_score = max(-2, min(2, final_score))
            confidence = max(0.0, confidence - 0.15)

        # Source credibility + recency decay
        confidence = apply_source_credibility(confidence, source_name)
        confidence = apply_recency_decay(confidence, article.age_hours or 0)

        # Merge AI tickers with regex-extracted tickers from scraper
        raw = article.raw_tickers or []
        tickers = clean_tickers(list(set(raw + ai_tickers)), text=full_text)

    else:
        # ── Graceful fallback: heuristic-only ──────────────────────────
        direction  = guess_direction(title, text)
        event_type = guess_event_type(title, text)
        sent_num   = {"positive": 1, "negative": -1, "neutral": 0}.get(h_sentiment, 0)
        final_score = max(-5, min(5, round(sent_num * 2 + h_impact)))

        # Align score sign with direction
        if direction == "positive" and final_score < 0:
            final_score = abs(final_score)
        if direction == "negative" and final_score > 0:
            final_score = -abs(final_score)

        confidence = min(1.0, 0.4 + abs(final_score) * 0.1)
        confidence = apply_source_credibility(confidence, source_name)
        confidence = apply_recency_decay(confidence, article.age_hours or 0)

        tickers    = clean_tickers(article.raw_tickers or [], text=full_text)
        divergence = False
        magnitude  = "high" if h_impact > 0.7 else "medium" if h_impact > 0.3 else "low"
        sector     = ""
        ai_result  = None  # make explicit for the reasoning line below
        reasoning  = (
            f"Heuristic-only (AI unavailable). "
            f"Direction: {direction}, type: {event_type}, "
            f"h_sentiment: {h_sentiment}, h_impact: {h_impact:.2f}"
        )

    return {
        "subject":          title,
        "event_type":       event_type,
        "tickers":          tickers,
        "impact_direction": direction,
        "signal_score":     final_score,
        "confidence":       round(confidence, 2),
        "verdict":          heuristic_verdict(final_score),
        "heuristic_impact": round(h_impact, 2),
        "divergence_flag":  divergence,
        "sources":          [source_name],
        "articles":         [article.url] if article.url else [],
        "timestamp":        article.published_at or datetime.now(timezone.utc).isoformat(),
        "reasoning":        reasoning if ai_result is None else (ai_result.get("reasoning", "")),
        "magnitude":        magnitude,
        "sector_impact":    sector,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FinScrape -> Dashboard Push")
    parser.add_argument("--url",         default=DEFAULT_URL,
                        help=f"Dashboard URL (default: {DEFAULT_URL})")
    parser.add_argument("--api-key",     default=DEFAULT_KEY,
                        help="API key for event ingestion")
    parser.add_argument("--limit",       type=int,   default=30,
                        help="Max articles per source (default: 30)")
    parser.add_argument("--age-hours",   type=float, default=2.0,
                        help="Only include articles within last N hours (default: 2.0)")
    parser.add_argument("--no-ai",       action="store_true",
                        help="Heuristic-only mode — skip all AI calls")
    parser.add_argument("--concurrency", type=int,   default=1,
                        help="Parallel AI calls (default: 1, useful range: 2-4)")
    parser.add_argument("--sources",     nargs="+",  default=None,
                        help="Limit to specific sources e.g. --sources yahoo cnbc")
    args = parser.parse_args()

    dashboard_url = args.url.rstrip("/")
    api_key       = args.api_key
    use_ai        = not args.no_ai

    print(f"\nFinScrape -> Dashboard Push — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Dashboard : {dashboard_url}")
    print(f"AI mode   : {'enabled' if use_ai else 'disabled (--no-ai)'}")
    if args.concurrency > 1:
        print(f"Concurrency: {args.concurrency} parallel AI calls")
    print()

    # Filter sources if --sources flag provided
    active_sources = SOURCES
    if args.sources:
        active_sources = [(n, c) for n, c in SOURCES if n in args.sources]
        if not active_sources:
            print(f"ERROR: None of the specified sources found: {args.sources}")
            return

    # Scrape all sources, collect fresh articles
    fresh_articles: list[tuple] = []  # (article, source_name)
    for source_name, Cls in active_sources:
        try:
            print(f"  Scraping {source_name}...", end=" ", flush=True)
            articles = Cls(max_articles=args.limit).scrape_news()
            fresh = [a for a in articles
                     if a.age_hours is None or a.age_hours <= args.age_hours]
            print(f"{len(articles)} articles, {len(fresh)} within {args.age_hours:.0f}h window")
            for a in fresh:
                fresh_articles.append((a, source_name))
        except Exception as e:
            print(f"FAILED: {e}")

    print(f"\n  Total fresh articles: {len(fresh_articles)}")

    if not fresh_articles:
        print("  No articles to process.")
        return

    # Process articles — serial or parallel
    all_events: list[dict] = []

    def process_one(pair):
        article, source_name = pair
        try:
            return article_to_event(article, source_name, use_ai=use_ai)
        except Exception as e:
            logging.warning("article_to_event failed for %s: %s", source_name, e)
            return None

    if args.concurrency > 1:
        print(f"  Processing with concurrency={args.concurrency}...")
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for event in pool.map(process_one, fresh_articles):
                if event and event.get("subject"):
                    all_events.append(event)
    else:
        for pair in fresh_articles:
            event = process_one(pair)
            if event and event.get("subject"):
                all_events.append(event)

    print(f"  Events ready to push: {len(all_events)}")

    if not all_events:
        print("  No events to push.")
        return

    # Push to dashboard
    print(f"\n  Pushing to {dashboard_url}/api/events...", end=" ", flush=True)
    try:
        resp = requests.post(
            f"{dashboard_url}/api/events",
            json={"events": all_events},
            headers={
                "Content-Type": "application/json",
                "X-API-Key":    api_key,
            },
            timeout=30,
        )
        print(f"HTTP {resp.status_code}")
        print(f"  Response: {resp.text[:300]}")
    except Exception as e:
        print(f"FAILED: {e}")

    # Summary table
    ai_count  = sum(1 for e in all_events if "AI unavailable" not in e.get("reasoning", ""))
    heur_count = len(all_events) - ai_count
    print(f"\n{'='*65}")
    print(f"  AI-scored: {ai_count}  |  Heuristic-only: {heur_count}  |  Total: {len(all_events)}")
    print(f"{'='*65}")
    for ev in sorted(all_events, key=lambda e: e["timestamp"], reverse=True)[:10]:
        tickers = ", ".join(ev["tickers"]) if ev["tickers"] else "---"
        arrow   = "+" if ev["signal_score"] >= 0 else ""
        div     = " [DIV]" if ev.get("divergence_flag") else ""
        print(f"  [{ev['verdict']:8s}] {arrow}{ev['signal_score']}{div} | {ev['subject'][:65]}")
        print(f"  {ev['sources'][0]:12s} | tickers: {tickers}")
    if len(all_events) > 10:
        print(f"  ... and {len(all_events) - 10} more")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
