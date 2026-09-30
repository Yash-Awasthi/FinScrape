"""
Advanced validation layer with NLP-informed scoring.

Replaces naive keyword bag-of-words with:
  - Sentence-level sentiment with negation handling
  - Financial magnitude extraction from actual numbers
  - Source credibility weighting
  - Recency-based confidence decay
  - Multi-signal aggregation across articles covering the same event
"""

from __future__ import annotations

import math
import re

from finscrape.analysis.constants import (
    EVENT_BASE_IMPACT,
    MAGNITUDE_THRESHOLDS,
    MAGNITUDE_WORDS,
    NEGATION_WINDOW,
    NEGATION_WORDS,
    NEGATIVE_STRONG,
    NEGATIVE_WEAK,
    POSITIVE_STRONG,
    POSITIVE_WEAK,
    RECENCY_DECAY_RATE,
    RECENCY_MAX_AGE_HOURS,
    SOURCE_CREDIBILITY,
    TICKER_STOPWORDS,
)

# ---------------------------------------------------------------------------
# Sentence-level sentiment with negation awareness
# ---------------------------------------------------------------------------

def _tokenize_sentences(text: str) -> list[str]:
    """Split text into rough sentences."""
    return re.split(r'(?<=[.!?])\s+', text)


def _check_negation(words: list[str], pos: int) -> bool:
    """Check if a word at position `pos` is negated by a preceding negation word."""
    start = max(0, pos - NEGATION_WINDOW)
    window = words[start:pos]
    window_text = " ".join(window).lower()
    for neg in NEGATION_WORDS:
        if neg in window_text:
            return True
    return False


def _score_sentence(sentence: str) -> float:
    """
    Score a single sentence for sentiment.
    Returns a float: positive values = bullish, negative = bearish.
    Handles negation: "not profitable" flips the positive signal.
    """
    sent_lower = sentence.lower()
    words = sent_lower.split()
    score = 0.0

    # Check multi-word phrases first (strong signals)
    for phrase in POSITIVE_STRONG:
        if " " in phrase and phrase in sent_lower:
            # Check if the phrase region is negated
            idx = sent_lower.find(phrase)
            word_pos = len(sent_lower[:idx].split())
            if _check_negation(words, word_pos):
                score -= 2.0  # negated strong positive = strong negative
            else:
                score += 2.0

    for phrase in NEGATIVE_STRONG:
        if " " in phrase and phrase in sent_lower:
            idx = sent_lower.find(phrase)
            word_pos = len(sent_lower[:idx].split())
            if _check_negation(words, word_pos):
                score += 2.0  # negated strong negative = strong positive
            else:
                score -= 2.0

    for phrase in POSITIVE_WEAK:
        if " " in phrase and phrase in sent_lower:
            idx = sent_lower.find(phrase)
            word_pos = len(sent_lower[:idx].split())
            if _check_negation(words, word_pos):
                score -= 1.0
            else:
                score += 1.0

    for phrase in NEGATIVE_WEAK:
        if " " in phrase and phrase in sent_lower:
            idx = sent_lower.find(phrase)
            word_pos = len(sent_lower[:idx].split())
            if _check_negation(words, word_pos):
                score += 1.0
            else:
                score -= 1.0

    # Single-word checks with position-aware negation
    for i, word in enumerate(words):
        # Skip multi-word phrases already counted
        if any(word in phrase and " " in phrase for phrase in
               POSITIVE_STRONG | NEGATIVE_STRONG | POSITIVE_WEAK | NEGATIVE_WEAK):
            # Only skip if this word was part of a matched multi-word phrase
            pass

        negated = _check_negation(words, i)

        if word in {w for w in POSITIVE_STRONG if " " not in w}:
            score += -2.0 if negated else 2.0
        elif word in {w for w in NEGATIVE_STRONG if " " not in w}:
            score += 2.0 if negated else -2.0
        elif word in {w for w in POSITIVE_WEAK if " " not in w}:
            score += -1.0 if negated else 1.0
        elif word in {w for w in NEGATIVE_WEAK if " " not in w}:
            score += 1.0 if negated else -1.0

    return score


def calculate_sentence_sentiment(text: str) -> tuple[str, float]:
    """
    Compute sentence-level sentiment with negation handling.

    Blends two engines: the phrase-list scorer below (strong/weak financial
    phrases, negation window) and the finance-aware lexicon engine from
    services.sentiment_analyzer (intensifiers, financial-context boost).
    Their disagreement dampens the combined score instead of trusting either.

    Returns: (sentiment_label, raw_score)
        sentiment_label: "positive", "negative", or "neutral"
        raw_score: unbounded float, magnitude indicates strength
    """
    sentences = _tokenize_sentences(text)
    legacy_score = sum(_score_sentence(s) for s in sentences)

    try:
        from finscrape.services.sentiment_analyzer import SentimentAnalyzer

        engine_score = SentimentAnalyzer.analyze_text(text).score  # -1..1
        combined = 0.5 * legacy_score + 2.0 * engine_score
    except Exception:  # noqa: BLE001 — engine unavailable: legacy score only
        combined = legacy_score

    if combined >= 1.5:
        return "positive", combined
    elif combined <= -1.5:
        return "negative", combined
    else:
        return "neutral", combined


# ---------------------------------------------------------------------------
# Market-relevance gate
# ---------------------------------------------------------------------------

# Lifestyle/clickbait patterns that should never become market events.
_OFF_TOPIC_PATTERNS = (
    r"\brecipes?\b", r"\bnutrition\w*\b", r"\banti[- ]inflammatory\b",
    r"\bworkout\w*\b", r"\bhoroscope\b", r"\bcelebrit\w*\b",
    r"\bmovie review\b", r"\bnetflix series\b", r"\bdating\b",
    r"\b(i |we )?(swear by|swears by)\b", r"\bessential foods\b",
    r"\bbest (restaurants|vacation|haircut|skincare)\b",
)

# Transient event briefs (quakes, storms) that only matter when a MARKET angle
# is present — insurers, commodities, macro damage figures.
_TRANSIENT_EVENT_PATTERNS = (
    r"\bm\s?\d+(\.\d+)?\s+earthquake\b", r"\bearthquake\b", r"\bquake\b",
    r"\bmagnitude[- ]?\d", r"\btropical (storm|depression)\b",
    r"\bhurricane \w+ (forms|approaches|makes landfall)\b",
    r"\bvolcan\w+ erupt\w*\b", r"\btsunami (warning|alert)\b",
)

_MARKET_ANGLE_PATTERNS = (
    r"\binsurer\w*\b", r"\b(re)?insurance\b", r"\bcommodit\w+\b",
    r"\b(oil|gas|copper|wheat|coffee) price\w*\b", r"\bsupply chain\w*\b",
    r"\beconom\w+\b", r"\b(export|import)s?\b", r"\bdamage\w*\b",
    r"\b\$\s?\d+(\.\d+)?\s?(billion|million|bn)\b", r"\bgdp\b",
    r"\bmarkets?\b", r"\bstocks?\b", r"\bshares?\b", r"\b(bond|yield)s?\b",
    r"\binflation\b", r"\breconstruction\b",
)


def is_market_relevant(title: str, text: str) -> bool:
    """Cheap pre-LLM gate: False for off-topic lifestyle pieces and transient
    event briefs (minor quakes, forming storms) that carry no market angle.

    Runs before any AI call so junk never costs tokens or lands in the DB.
    """
    combined = f"{title}. {text}".lower()
    if any(re.search(p, combined) for p in _OFF_TOPIC_PATTERNS):
        return False
    if any(re.search(p, combined) for p in _TRANSIENT_EVENT_PATTERNS):
        return any(re.search(p, combined) for p in _MARKET_ANGLE_PATTERNS)
    return True


# ---------------------------------------------------------------------------
# Financial magnitude extraction
# ---------------------------------------------------------------------------

def extract_financial_magnitudes(text: str) -> dict:
    """
    Parse actual financial figures from text and categorize their magnitude.

    Returns dict with keys like:
        {"dollar_amount": 4.2e9, "dollar_magnitude": "high",
         "percentage_beat": 12.0, "percentage_magnitude": "high",
         "layoff_count": 50000, "layoff_magnitude": "high"}
    """
    results = {}
    text_lower = text.lower()

    # Dollar amounts — billions
    billion_patterns = [
        r'\$\s*([\d,.]+)\s*(?:billion|b|bn)\b',
        r'([\d,.]+)\s*billion\s*(?:dollars?|\$)',
    ]
    for pat in billion_patterns:
        match = re.search(pat, text_lower)
        if match:
            try:
                val = float(match.group(1).replace(",", ""))
                results["dollar_amount"] = val * 1e9
                thresholds = MAGNITUDE_THRESHOLDS["dollar_billions"]
                if val >= thresholds["high"]:
                    results["dollar_magnitude"] = "high"
                elif val >= thresholds["medium"]:
                    results["dollar_magnitude"] = "medium"
                else:
                    results["dollar_magnitude"] = "low"
                break
            except ValueError:
                pass

    # Dollar amounts — millions
    if "dollar_amount" not in results:
        million_patterns = [
            r'\$\s*([\d,.]+)\s*(?:million|m|mn)\b',
            r'([\d,.]+)\s*million\s*(?:dollars?|\$)',
        ]
        for pat in million_patterns:
            match = re.search(pat, text_lower)
            if match:
                try:
                    val = float(match.group(1).replace(",", ""))
                    results["dollar_amount"] = val * 1e6
                    thresholds = MAGNITUDE_THRESHOLDS["dollar_millions"]
                    if val >= thresholds["high"]:
                        results["dollar_magnitude"] = "high"
                    elif val >= thresholds["medium"]:
                        results["dollar_magnitude"] = "medium"
                    else:
                        results["dollar_magnitude"] = "low"
                    break
                except ValueError:
                    pass

    # Percentage beats/misses
    pct_patterns = [
        r'(?:beat|exceeded|topped|surpassed|missed)\s+(?:by\s+)?([\d,.]+)\s*%',
        r'([\d,.]+)\s*%\s+(?:beat|above|below|miss)',
        r'(?:up|down|rose|fell|gained|lost|jumped|dropped)\s+([\d,.]+)\s*%',
    ]
    for pat in pct_patterns:
        match = re.search(pat, text_lower)
        if match:
            try:
                val = float(match.group(1).replace(",", ""))
                results["percentage_value"] = val
                thresholds = MAGNITUDE_THRESHOLDS["percentage_beat"]
                if val >= thresholds["high"]:
                    results["percentage_magnitude"] = "high"
                elif val >= thresholds["medium"]:
                    results["percentage_magnitude"] = "medium"
                else:
                    results["percentage_magnitude"] = "low"
                break
            except ValueError:
                pass

    # Layoff counts
    layoff_patterns = [
        r'(?:lay\s*off|cut|eliminate|reduce)\s*(?:up\s+to\s+)?([\d,]+)\s*(?:jobs?|employees?|workers?|positions?|staff)',
        r'([\d,]+)\s*(?:jobs?|employees?|workers?|positions?)\s*(?:cut|eliminated|lost|laid off)',
    ]
    for pat in layoff_patterns:
        match = re.search(pat, text_lower)
        if match:
            try:
                val = int(match.group(1).replace(",", ""))
                results["layoff_count"] = val
                thresholds = MAGNITUDE_THRESHOLDS["layoff_count"]
                if val >= thresholds["high"]:
                    results["layoff_magnitude"] = "high"
                elif val >= thresholds["medium"]:
                    results["layoff_magnitude"] = "medium"
                else:
                    results["layoff_magnitude"] = "low"
                break
            except ValueError:
                pass

    # Overall magnitude (highest of any extracted)
    mag_order = {"high": 3, "medium": 2, "low": 1}
    best_mag = "low"
    for key in results:
        if key.endswith("_magnitude"):
            if mag_order.get(results[key], 0) > mag_order.get(best_mag, 0):
                best_mag = results[key]
    results["overall_magnitude"] = best_mag

    return results


# ---------------------------------------------------------------------------
# Source credibility weighting
# ---------------------------------------------------------------------------

def get_source_credibility(source_name: str) -> float:
    """
    Return credibility weight for a news source (0.0–1.0).
    Higher = more trustworthy.
    """
    return SOURCE_CREDIBILITY.get(
        source_name.lower(),
        SOURCE_CREDIBILITY["_default"],
    )


def apply_source_credibility(confidence: float, source_name: str) -> float:
    """
    Adjust AI confidence based on source credibility.
    Multiplier is confidence * (0.7 + 0.3 * credibility), which is <= 1.0 always —
    this can only discount confidence, never boost it above the input.
    """
    credibility = get_source_credibility(source_name)
    # Blend: 70% AI confidence, 30% source credibility influence
    adjusted = confidence * 0.7 + confidence * credibility * 0.3
    return round(min(1.0, max(0.0, adjusted)), 2)


# ---------------------------------------------------------------------------
# Recency decay
# ---------------------------------------------------------------------------

def calculate_recency_multiplier(age_hours: float | None) -> float:
    """
    Compute a time-based confidence multiplier.
    Fresh articles (< 1h) get ~1.0; older articles decay exponentially.
    Returns a multiplier in (0.0, 1.0].
    """
    if age_hours is None:
        return 0.85  # unknown age = moderate discount
    age_hours = min(max(0.0, age_hours), RECENCY_MAX_AGE_HOURS)
    return math.exp(-RECENCY_DECAY_RATE * age_hours)


def apply_recency_decay(confidence: float, age_hours: float | None) -> float:
    """Apply recency decay to a confidence score."""
    multiplier = calculate_recency_multiplier(age_hours)
    return round(confidence * multiplier, 2)


def fuse_confidence(
    base: float,
    source: str,
    age_hours: float | None,
    divergence: bool,
    breaking: bool,
) -> float:
    """
    Combine all confidence adjustments in one place.
    Multipliers (source credibility, recency) apply first; additive
    penalty/boost (divergence, breaking) apply last on the multiplied result,
    so a -0.15 divergence penalty always costs 0.15, not a fraction of it.
    """
    confidence = apply_source_credibility(base, source)
    confidence = apply_recency_decay(confidence, age_hours)
    if divergence:
        confidence -= 0.15
    if breaking:
        confidence += 0.10
    return round(min(1.0, max(0.0, confidence)), 2)


# ---------------------------------------------------------------------------
# Multi-signal aggregation
# ---------------------------------------------------------------------------

def aggregate_signals(events: list[dict]) -> dict:
    """
    When multiple articles cover the same event, aggregate their signals.

    Takes a list of analysis dicts for the same event and returns
    a merged signal with boosted confidence and averaged scores.
    """
    if not events:
        return {}
    if len(events) == 1:
        return events[0]

    # Use the highest-confidence analysis as the base
    base = max(events, key=lambda e: e.get("confidence", 0))
    result = dict(base)

    # Confidence boost: each additional source increases confidence
    # Diminishing returns: +0.05 per extra source, capped at 1.0
    n_extra = len(events) - 1
    confidence_boost = min(0.15, n_extra * 0.05)
    result["confidence"] = min(1.0, result.get("confidence", 0.5) + confidence_boost)

    # Merge tickers from all analyses
    all_tickers = set()
    for e in events:
        all_tickers.update(e.get("tickers", []))
    result["tickers"] = list(all_tickers)

    # Merge affected entities (deduplicate by name)
    seen_entities = set()
    merged_entities = []
    for e in events:
        for entity in e.get("affected_entities", []):
            name = entity.get("name", "")
            if name and name not in seen_entities:
                seen_entities.add(name)
                merged_entities.append(entity)
    result["affected_entities"] = merged_entities

    # Merge second-order effects (deduplicate)
    all_effects = set()
    for e in events:
        all_effects.update(e.get("second_order_effects", []))
    result["second_order_effects"] = list(all_effects)

    # Merge sources and articles
    all_sources = set()
    all_articles = set()
    for e in events:
        all_sources.update(e.get("sources", []))
        all_articles.update(e.get("articles", []))
    result["sources"] = list(all_sources)
    result["articles"] = list(all_articles)

    # Average signal score (weighted by confidence)
    total_weight = sum(e.get("confidence", 0.5) for e in events)
    if total_weight > 0:
        weighted_score = sum(
            e.get("signal_score", 0) * e.get("confidence", 0.5)
            for e in events
        ) / total_weight
        result["signal_score"] = round(weighted_score)

    # Merge key_metrics (union)
    merged_metrics = {}
    for e in events:
        merged_metrics.update(e.get("key_metrics", {}))
    result["key_metrics"] = merged_metrics

    return result


# ---------------------------------------------------------------------------
# Legacy-compatible heuristic score (updated with negation support)
# ---------------------------------------------------------------------------

def calculate_heuristic_score(text: str, event_type: str) -> tuple[str, float]:
    """
    Calculate heuristic sentiment and impact score from text.

    Now uses sentence-level sentiment with negation awareness
    instead of simple bag-of-words.

    Returns: (sentiment_label, impact_score)
        sentiment_label: "positive", "negative", or "neutral"
        impact_score: float in [0, 1]
    """
    # Sentence-level sentiment with negation
    sentiment, raw_score = calculate_sentence_sentiment(text)

    # Impact calculation (logistic weighting) — enhanced with magnitude extraction
    base_impact = EVENT_BASE_IMPACT.get(event_type, 0.3)
    text_lower = text.lower()

    mag_boost = sum(1 for w in MAGNITUDE_WORDS if w in text_lower) * 0.1

    # Extract actual financial figures for more precise boosting
    magnitudes = extract_financial_magnitudes(text)
    figure_boost = 0.0
    if magnitudes.get("dollar_magnitude") == "high":
        figure_boost = 0.35
    elif magnitudes.get("dollar_magnitude") == "medium":
        figure_boost = 0.15
    elif magnitudes.get("dollar_magnitude") == "low":
        figure_boost = 0.05

    if magnitudes.get("percentage_magnitude") == "high":
        figure_boost = max(figure_boost, 0.25)
    elif magnitudes.get("percentage_magnitude") == "medium":
        figure_boost = max(figure_boost, 0.1)

    if magnitudes.get("layoff_magnitude") == "high":
        figure_boost = max(figure_boost, 0.3)
    elif magnitudes.get("layoff_magnitude") == "medium":
        figure_boost = max(figure_boost, 0.15)

    logit_base = math.log(base_impact / (1.0 - base_impact + 1e-9))
    heuristic_impact = 1.0 / (1.0 + math.exp(-(logit_base + mag_boost + figure_boost)))

    return sentiment, round(heuristic_impact, 2)


def check_divergence(ai_sentiment: str, heuristic_sentiment: str) -> bool:
    """Flag if AI and heuristics disagree on polarity."""
    if ai_sentiment == "neutral" or heuristic_sentiment == "neutral":
        return False
    # "mixed" from AI is not a divergence
    if ai_sentiment == "mixed":
        return False
    return ai_sentiment != heuristic_sentiment


# ---------------------------------------------------------------------------
# Deterministic anti-hallucination: reasoning vs. computed indicator facts
# ---------------------------------------------------------------------------

# Only indicator keys market_data.compute_indicators actually emits — never
# extend this to free-form claims, that needs real number-linking, not regex.
_INDICATOR_ALIASES = {
    "rsi14": ("rsi",),
    "sma20": ("sma20", "sma 20", "20-day sma", "20 day sma"),
    "sma50": ("sma50", "sma 50", "50-day sma", "50 day sma"),
    "atr_pct": ("atr",),
    "ret_5d": ("5-day return", "5 day return", "5d return"),
    "pct_from_52w_high": ("52-week high", "52 week high", "52w high"),
}


def check_number_conflicts(reasoning: str, facts: dict) -> list[str]:
    """Flag reasoning that states a number for a computed indicator that does not
    match what we actually computed.

    ponytail: regex only catches the "NAME ... number" shape within a short window
    (e.g. "RSI is 82"), not indirect phrasing or numbers separated across sentences.
    Ceiling: false negatives on phrasing we don't match, occasional false positive on
    short aliases like "atr" inside an unrelated word. Upgrade path: real number-linking
    (NER over the reasoning) if either starts costing real accuracy.
    """
    if not reasoning or not facts:
        return []
    text_lower = reasoning.lower()
    conflicts = []
    for key, value in facts.items():
        if value is None or key not in _INDICATOR_ALIASES:
            continue
        for alias in _INDICATOR_ALIASES[key]:
            pattern = r"\b" + re.escape(alias) + r"[^\d\n]{0,15}(-?\d+(?:\.\d+)?)"
            for match in re.finditer(pattern, text_lower):
                stated = float(match.group(1))
                tolerance = max(0.5, abs(float(value)) * 0.05)
                if abs(stated - float(value)) > tolerance:
                    conflicts.append(f"{key}: reasoning says {stated}, computed {value}")
    return conflicts


# Symbols like RELIANCE.NS or BRK-B, not indices (^GSPC); the LLM writes N/A, NONE or a dash for
# entities that are not listed.
_TICKER_SHAPE = re.compile(r"[A-Z0-9][A-Z0-9.=-]{0,14}")
_PLACEHOLDERS = frozenset({"NA", "NONE", "NULL", "TBD", "UNKNOWN", "PRIVATE", "UNLISTED"})


def clean_tickers(tickers: list[str], text: str = "") -> list[str]:
    """Remove noise tickers using the stopword list.

    A stopword written as explicit trader shorthand ($NOW, (NOW)) in `text`
    is real signal, not bare prose picking up an English word — keep it.
    """
    protected = set(re.findall(r"\$([A-Z]{1,5})\b", text))
    protected.update(re.findall(r"\(([A-Z]{1,5})\)", text))
    # Indices (^GSPC) are benchmarks, not positions anyone can take.
    return [
        t for t in tickers
        if _TICKER_SHAPE.fullmatch(t.upper())
        and t.upper() not in _PLACEHOLDERS
        and (t.upper() in protected or t.upper() not in TICKER_STOPWORDS)
    ]


_COMPANY_SUFFIX = re.compile(
    r"[,.]?\s+(inc|corp|corporation|co|company|ltd|plc|group|holdings|sa|ag|nv)\.?$",
    re.IGNORECASE,
)


def grounded_tickers(
    llm: list[str], entities: list[dict], from_text: list[str], text: str
) -> list[str]:
    """LLM tickers the article backs, by a text-derived source or by the company name
    the LLM gave. A small model free-associates megacaps (NVDA on a Gaza shooting)."""
    text_lower = text.lower()
    named: set[str] = set()
    for e in entities:
        name = str(e.get("name") or "").strip()
        while (core := _COMPANY_SUFFIX.sub("", name)) != name:
            name = core
        ticker = e.get("ticker")
        if (
            len(name) >= 3
            and re.search(rf"\b{re.escape(name.lower())}\b", text_lower)
            and _ticker_is(ticker, name)
        ):
            named.add(ticker)
    backed = set(from_text) | named
    return [t for t in dict.fromkeys(llm) if t in backed]


def _ticker_is(ticker: object, name: str) -> bool:
    """The LLM writes a symbol for unlisted names (flydubai "FZ") or borrows another
    issuer's (Vanguard "VGI"), so the curated map or the SEC title must agree."""
    from finscrape.analysis.ticker_map import resolve_company_tickers
    from finscrape.entity_map import listed_titles

    if not isinstance(ticker, str):
        return False
    if ticker in resolve_company_tickers(name):
        return True
    title = listed_titles().get(ticker.upper(), "").split()
    head = re.sub(r"[^a-z0-9]", "", title[0].lower()) if title else ""
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    return (len(head) >= 2 and compact.startswith(head)) or (
        len(compact) >= 3 and head.startswith(compact)
    )
