"""Sector/geopolitics keyword → ticker resolution (Phase 12).

The gap this fills: a geopolitics headline ("Iran closes the Strait of Hormuz") resolves
role-tagged affected_entities but the LLM often leaves the per-entity `ticker` blank
(it emits sector *names*, not symbols), so `_analyze_article` drops the event at the
"No valid tickers found" gate. This module maps the sector/region words that ARE in the
text to liquid ticker proxies, so the event keeps tickers and survives the gate.

Two consumers:
  - `resolve_tickers(text)` — forward map, added to the pipeline's ticker fusion.
  - `keywords_for_ticker(symbol)` — reverse map, powers
    `server.correlate.find_news_for_market_symbol` → `explained_market_move`.

Plus company-name resolution (Phase 13 wiring, data from the absorbed
company_name_to_ticker repo — the official SEC company_tickers.json):
  - `resolve_company_tickers(text)` — matches full legal company names
    ("NVIDIA CORP", "Alphabet Inc.") in the text and returns their tickers.
    Complements the keyword map: catches articles that name the company outright.

Pure + data-driven (finscrape/data/entity_index.json + SEC company_tickers.json);
no network, no DB. Matching is case-insensitive: single alnum tokens match on word
boundaries, multi-word phrases as substrings.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

_DATA_FILE = Path(__file__).with_name("data") / "entity_index.json"
# Official SEC company→ticker list, absorbed from company_name_to_ticker (768 KB,
# ~10k companies). Kept in the absorbed tree so it stays next to its provenance.
_COMPANY_FILE = (
    Path(__file__).with_name("absorbed")
    / "market_data"
    / "company_name_to_ticker"
    / "company_tickers.json"
)


@functools.lru_cache(maxsize=1)
def _forward() -> dict[str, tuple[str, ...]]:
    """keyword(lowercased) → tuple of uppercase tickers. Ignores `_`-prefixed meta keys."""
    raw = json.loads(_DATA_FILE.read_text())
    out: dict[str, tuple[str, ...]] = {}
    for keyword, tickers in raw.items():
        if keyword.startswith("_") or not isinstance(tickers, list):
            continue
        syms = tuple(sorted({str(t).upper() for t in tickers if str(t).strip()}))
        if syms:
            out[keyword.lower()] = syms
    return out


@functools.lru_cache(maxsize=1)
def _reverse() -> dict[str, tuple[str, ...]]:
    """ticker → tuple of keywords that map to it (for find_news_for_market_symbol)."""
    rev: dict[str, set[str]] = {}
    for keyword, tickers in _forward().items():
        for t in tickers:
            rev.setdefault(t, set()).add(keyword)
    return {t: tuple(sorted(kws)) for t, kws in rev.items()}


def _matches(keyword: str, text_lower: str) -> bool:
    """Word-boundary match for single alnum tokens; substring for multi-word phrases."""
    if " " in keyword:
        return keyword in text_lower
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text_lower) is not None


def resolve_tickers(text: str) -> list[str]:
    """Tickers implied by any sector/region keyword present in `text`. Sorted, unique."""
    text_lower = (text or "").lower()
    if not text_lower:
        return []
    found: set[str] = set()
    for keyword, tickers in _forward().items():
        if _matches(keyword, text_lower):
            found.update(tickers)
    return sorted(found)


# Headline plus roughly the first two sentences. A keyword deep in the body is
# usually background ("amid the U.S.-Iran war"), not what the story is about.
LEDE_CHARS = 280


def lede_tickers(title: str, text: str) -> list[str]:
    """`resolve_tickers` over the headline and lede only."""
    return resolve_tickers(f"{title} {(text or '')[:LEDE_CHARS]}")


def keywords_for_ticker(symbol: str) -> list[str]:
    """Keywords/phrases associated with a ticker — the reverse of resolve_tickers."""
    return list(_reverse().get((symbol or "").upper(), ()))


def tickers_for_keyword(keyword: str) -> list[str]:
    """Tickers mapped to one exact keyword (no text scanning — `resolve_tickers` does that).

    Lets a caller holding its own keyword vocabulary bridge into this index, e.g.
    `server.correlate` mapping its topic keywords onto the tickers they imply.
    """
    return list(_forward().get((keyword or "").lower(), ()))


# ── Company-name resolution (SEC company_tickers.json) ────────────────────────

@functools.lru_cache(maxsize=1)
def _company_names() -> dict[str, str]:
    """lowercased company name → ticker. Names < 5 chars skipped (false-positive
    bait: "arm", "it"); share-class variants collapse to their first ticker."""
    try:
        raw = json.loads(_COMPANY_FILE.read_text(encoding="utf-8"))
    except OSError:
        return {}
    out: dict[str, str] = {}
    for row in raw.values():
        if not isinstance(row, dict):
            continue
        name = str(row.get("title") or row.get("name") or "").strip().lower()
        ticker = str(row.get("ticker") or "").strip().upper()
        if len(name) >= 5 and len(ticker) <= 5:
            out.setdefault(name, ticker)
    return out


@functools.lru_cache(maxsize=1)
def listed_titles() -> dict[str, str]:
    """Ticker → SEC company title."""
    try:
        raw = json.loads(_COMPANY_FILE.read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {
        str(row.get("ticker") or "").strip().upper(): str(row.get("title") or "")
        for row in raw.values()
        if isinstance(row, dict)
    }


def listed_symbols() -> frozenset[str]:
    """Every ticker on the SEC list."""
    return frozenset(listed_titles())


@functools.lru_cache(maxsize=1)
def _company_regex() -> re.Pattern | None:
    """One alternation over all company names, longest-first so
    'alphabet inc. class a capital stock' wins over its 'alphabet inc.' prefix."""
    names = sorted(_company_names(), key=len, reverse=True)
    if not names:
        return None
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(n) for n in names) + r")(?![a-z0-9])")


def resolve_company_tickers(text: str) -> list[str]:
    """Tickers for any full company name present in `text`. Sorted, unique.

    Word-boundary anchored (no alnum neighbors) so "NVIDIA CORP" matches but
    "nvidia" alone does not — the keyword map handles short names.
    """
    text_lower = (text or "").lower()
    rx = _company_regex()
    if not text_lower or rx is None:
        return []
    names = _company_names()
    return sorted({names[m.group(0)] for m in rx.finditer(text_lower)})
