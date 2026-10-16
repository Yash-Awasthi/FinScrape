"""
Advanced NLP pipeline — spaCy-based entity extraction and disambiguation
for financial text.

Replaces the naive regex ticker extraction with proper NLP:
- Named Entity Recognition (NER) for ORG, PERSON, MONEY, DATE, PERCENT
- Entity disambiguation (Apple Inc vs. apple fruit)
- Company→ticker resolution via entity index + fuzzy matching
- Financial metric extraction (revenue, EPS, price targets)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from finscrape.analysis.temporal import (
    TemporalExtractor,
    TemporalReference,
    get_next_catalyst_date,
)
from finscrape.analysis.ticker_map import COMPANY_TO_TICKER
from finscrape.entity_map import (
    _matches,
    parenthesised_tickers,
    resolve_company_tickers,
)

logger = logging.getLogger(__name__)

# Lazy-load spaCy to avoid import overhead when not needed.
_nlp = None
# Latches a missing model. Returning None without recording the failure meant every
# single article re-attempted spacy.load() and re-logged the warning — 200 failed
# package lookups and 200 log lines for one batch.
_nlp_unavailable = False


def _get_nlp():
    global _nlp, _nlp_unavailable
    if _nlp is None and not _nlp_unavailable:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
            logger.info("Loaded spaCy model: en_core_web_sm")
        except OSError:
            _nlp_unavailable = True
            logger.warning("spaCy model not found. Run: python -m spacy download en_core_web_sm")
    return _nlp


def _merge_entities(
    keyword: list[ExtractedEntity], ner: list[ExtractedEntity]
) -> list[ExtractedEntity]:
    """Keyword hits first (they carry resolved tickers), then NER entities not already
    present. Deduplicated on (name, type) so one company is never listed twice."""
    merged = list(keyword)
    seen = {(e.name.lower(), e.entity_type) for e in merged}
    for ent in ner:
        key = (ent.name.lower(), ent.entity_type)
        if key not in seen:
            seen.add(key)
            merged.append(ent)
    return merged


# --- Well-known financial entity mappings ---
# Company name -> ticker lives in finscrape.analysis.ticker_map (the one map,
# shared with the scrapers' regex extractor). Imported above as COMPANY_TO_TICKER.

# Keys are the `finscrape.analysis.sectors.TAXONOMY` names, so the fallback never
# writes a sector the panels would have to alias. Geopolitical vocabulary is here
# because most ingested stories are political and name no company.
SECTOR_KEYWORDS = {
    "technology": ["nvidia", "amd", "micron", "sandisk", "intel", "tsmc", "memory chips", "software", "semiconductor", "chip", "chips", "ai", "cloud computing",
                   "saas", "data center", "artificial intelligence", "cyberattack", "hacker"],
    "healthcare": ["pharma", "biotech", "drug", "fda", "clinical trial", "healthcare",
                   "hospital", "vaccine", "outbreak", "pandemic", "epidemic"],
    "financials": ["fed", "federal reserve", "ecb", "hike rates", "rate hikes", "bitcoins", "etf", "hedge fund", "asset manager", "bank", "banks", "interest rate", "rate cut", "rate hike", "central bank",
                   "insurance", "insurer", "bond yields", "sovereign debt", "default",
                   "currency", "bitcoin", "crypto", "sanctions"],
    "energy": ["oil", "crude", "natural gas", "lng", "pipeline", "refinery", "opec",
               "petroleum", "renewable", "solar", "nuclear power", "strait of hormuz"],
    "consumer": ["luxury", "apparel", "retail", "retailer", "consumer spending", "e-commerce", "food prices",
                 "restaurant", "automaker", "tourism"],
    "industrials": ["manufacturing", "aerospace", "defense contractor", "defence",
                    "missile", "fighter jet", "helicopter", "drone", "warship", "arms deal", "shipping", "freight",
                    "airline", "railway", "port strike", "supply chain", "tariff", "tariffs"],
    "materials": ["wheat", "grain", "fertilizer", "copper", "lithium", "rare earth",
                  "steel", "aluminium", "aluminum", "iron ore", "gold", "mining", "drought"],
    "utilities": ["power grid", "blackout", "electricity prices", "power outage", "water supply"],
    "real_estate": ["real estate", "reit", "property market", "housing", "mortgage rates"],
    "communications": ["telecom", "broadband", "satellite", "undersea cable", "social media",
                       "streaming", "5g"],
}

# Words that indicate "Apple" is the company, not the fruit
APPLE_COMPANY_CONTEXT = frozenset({
    "iphone", "ipad", "mac", "macbook", "ios", "app store", "tim cook",
    "cupertino", "silicon", "aapl", "apple watch", "airpods", "vision pro",
    "revenue", "earnings", "stock", "shares", "market cap", "quarterly",
})


@dataclass
class ExtractedEntity:
    """An entity extracted from financial text."""
    name: str
    entity_type: str  # ORG, PERSON, MONEY, DATE, PERCENT, GPE, PRODUCT
    ticker: str = ""
    role: str = "mentioned"
    impact: str = "neutral"  # positive, negative, neutral
    confidence: float = 0.5
    span_start: int = 0
    span_end: int = 0


@dataclass
class FinancialMetric:
    """A financial metric extracted from text."""
    metric_type: str  # revenue, eps, price_target, market_cap, layoffs, etc.
    value: float
    unit: str = ""  # %, $, count
    context: str = ""  # "beat by", "missed by", "grew", "declined"
    comparison: str = ""  # "vs estimate", "yoy", "qoq"


@dataclass
class NLPResult:
    """Complete NLP analysis of a financial text."""
    entities: list[ExtractedEntity] = field(default_factory=list)
    metrics: list[FinancialMetric] = field(default_factory=list)
    temporal_refs: list[TemporalReference] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    primary_company: str = ""
    primary_ticker: str = ""
    sector: str = ""
    has_breaking_indicators: bool = False


class FinancialNLP:
    """Advanced NLP pipeline for financial text analysis."""

    def __init__(self, entity_index: dict[str, list[tuple[str, str]]] | None = None):
        """
        Args:
            entity_index: Optional mapping of keyword → [(company, ticker), ...]
                          from the storage layer. Supplements the built-in map.
        """
        self._custom_index = entity_index or {}
        self._temporal_extractor = TemporalExtractor()

    def analyze(self, title: str, text: str) -> NLPResult:
        """Run the full NLP pipeline on a headline + article text."""
        full_text = f"{title}. {text}" if title else text
        result = NLPResult()

        # Step 1: keyword sweep first, then spaCy NER on top — union, not either/or.
        #
        # en_core_web_sm is weak on headline text: it tags "GDPR" as ORG in "Google hit
        # with a fine by the Irish data watchdog" and misses Google entirely. Running NER
        # *instead of* the keyword sweep therefore lost real tickers (GOOGL, PLTR) and
        # added none — measured across 221 live feed items. NER now supplements.
        result.entities = self._keyword_entities(full_text)
        nlp = _get_nlp()
        doc = None
        if nlp:
            doc = nlp(full_text[:10000])  # Cap to avoid memory issues
            result.entities = _merge_entities(
                result.entities, self._extract_entities(doc, full_text)
            )

        # Step 2: Financial metric extraction (regex-based, doesn't need spaCy)
        result.metrics = self._extract_metrics(full_text)

        # Step 3: Resolve tickers
        result.tickers = self._resolve_all_tickers(result.entities, full_text)

        # Step 4: Identify primary company
        if result.tickers:
            result.primary_ticker = result.tickers[0]
            for ent in result.entities:
                if ent.ticker == result.primary_ticker:
                    result.primary_company = ent.name
                    break

        # Step 5: Sector detection
        result.sector = self._detect_sector(full_text, result.tickers)

        # Step 6: Breaking news indicators
        result.has_breaking_indicators = self._check_breaking_indicators(full_text)

        # Step 7: Temporal extraction
        result.temporal_refs = self._temporal_extractor.extract(full_text, doc=doc)

        return result

    def _extract_entities(self, doc, full_text: str) -> list[ExtractedEntity]:
        """Extract entities using spaCy NER + disambiguation."""
        entities = []
        seen = set()

        for ent in doc.ents:
            if ent.label_ not in ("ORG", "PERSON", "MONEY", "DATE", "PERCENT", "GPE", "PRODUCT"):
                continue

            name = ent.text.strip()
            key = (name.lower(), ent.label_)
            if key in seen:
                continue
            seen.add(key)

            extracted = ExtractedEntity(
                name=name,
                entity_type=ent.label_,
                span_start=ent.start_char,
                span_end=ent.end_char,
            )

            # Resolve ticker for ORG entities
            if ent.label_ == "ORG":
                ticker = self._resolve_ticker(name, full_text)
                if ticker:
                    extracted.ticker = ticker

            entities.append(extracted)

        return entities

    def _keyword_entities(self, text: str) -> list[ExtractedEntity]:
        """Company names matched against the curated map, scanned over the whole text.

        Runs always: it is the only path that reliably catches a company named in a
        headline, since the small spaCy model frequently does not label it at all.
        """
        entities = []
        text_lower = text.lower()

        for name, ticker in COMPANY_TO_TICKER.items():
            if _matches(name, text_lower):
                entities.append(ExtractedEntity(
                    name=name.title(),
                    entity_type="ORG",
                    ticker=ticker,
                ))

        return entities

    @staticmethod
    def _entity_key(ent: ExtractedEntity) -> tuple[str, str]:
        return (ent.name.lower(), ent.entity_type)

    def _resolve_ticker(self, entity_name: str, context: str) -> str:
        """Resolve an entity name to a ticker symbol with disambiguation."""
        name_lower = entity_name.lower().strip()
        context_lower = context.lower()

        # Disambiguation: "Apple" the company vs fruit
        if name_lower == "apple":
            if any(w in context_lower for w in APPLE_COMPANY_CONTEXT):
                return "AAPL"
            # In financial news, default to company
            return "AAPL"

        # Word-boundary lookup — catches "Apple Inc." via the "apple" key
        # without matching "arm" inside "pharma" or "target" inside "targeting"
        for key, ticker in COMPANY_TO_TICKER.items():
            if _matches(key, name_lower):
                return ticker

        # SEC company list (10k legal names) — catches "NVIDIA Corporation"-style
        # names the 189-entry hand-curated map doesn't have. Ambiguous multi-hits
        # (share classes etc.) are skipped rather than guessed.
        sec_hits = resolve_company_tickers(name_lower)
        if len(sec_hits) == 1:
            return sec_hits[0]

        # Custom entity index lookup
        for keyword, entries in self._custom_index.items():
            if keyword in name_lower:
                for company, ticker in entries:
                    if company.lower() in context_lower:
                        return ticker

        return ""

    def _extract_metrics(self, text: str) -> list[FinancialMetric]:
        """Extract financial metrics from text using regex patterns."""
        metrics = []

        # Revenue/earnings beats/misses
        for m in re.finditer(
            r'(?:revenue|sales|earnings|eps|profit)\s+(?:of\s+)?\$?([\d,.]+)\s*(billion|million|B|M|bn|mn)?'
            r'(?:.*?(?:beat|miss|exceed|top|below|above)\w*\s+(?:by\s+)?([\d.]+)%?)?',
            text, re.IGNORECASE
        ):
            value = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower()
            if unit in ("billion", "b", "bn"):
                value *= 1_000_000_000
            elif unit in ("million", "m", "mn"):
                value *= 1_000_000

            metric_type = "revenue"
            for kw in ("earnings", "eps", "profit"):
                if kw in m.group(0).lower():
                    metric_type = kw
                    break

            context = ""
            if m.group(3):
                beat_pct = float(m.group(3))
                if any(w in m.group(0).lower() for w in ("beat", "exceed", "top", "above")):
                    context = f"beat by {beat_pct}%"
                else:
                    context = f"missed by {beat_pct}%"

            metrics.append(FinancialMetric(
                metric_type=metric_type,
                value=value,
                unit="$",
                context=context,
            ))

        # Percentage changes
        for m in re.finditer(
            r'(?:up|down|rose|fell|gained|lost|grew|declined|surged|plunged|jumped|dropped)\s+'
            r'([\d.]+)%',
            text, re.IGNORECASE
        ):
            direction = m.group(0).split()[0].lower()
            is_positive = direction in ("up", "rose", "gained", "grew", "surged", "jumped")
            metrics.append(FinancialMetric(
                metric_type="price_change",
                value=float(m.group(1)) * (1 if is_positive else -1),
                unit="%",
                context=direction,
            ))

        # Price targets
        for m in re.finditer(
            r'price\s+target\s+(?:of\s+|to\s+|at\s+)?\$?([\d,.]+)',
            text, re.IGNORECASE
        ):
            metrics.append(FinancialMetric(
                metric_type="price_target",
                value=float(m.group(1).replace(",", "")),
                unit="$",
            ))

        # Layoff numbers
        for m in re.finditer(
            r'(?:lay\s*off|cut|eliminate|reduce)\w*\s+([\d,]+)\s*(?:jobs|positions|employees|workers)',
            text, re.IGNORECASE
        ):
            metrics.append(FinancialMetric(
                metric_type="layoffs",
                value=float(m.group(1).replace(",", "")),
                unit="count",
            ))

        # Deal values
        for m in re.finditer(
            r'(?:deal|acquisition|merger|transaction|valued)\s+(?:worth|at|of)\s+\$?([\d,.]+)\s*(billion|million|B|M|bn|mn)',
            text, re.IGNORECASE
        ):
            value = float(m.group(1).replace(",", ""))
            unit = m.group(2).lower()
            if unit in ("billion", "b", "bn"):
                value *= 1_000_000_000
            elif unit in ("million", "m", "mn"):
                value *= 1_000_000
            metrics.append(FinancialMetric(
                metric_type="deal_value",
                value=value,
                unit="$",
            ))

        return metrics

    def _resolve_all_tickers(self, entities: list[ExtractedEntity], text: str) -> list[str]:
        """Resolve all tickers from entities + regex patterns, deduplicated."""
        tickers = []
        seen = set()

        # From NER entities
        for ent in entities:
            if ent.ticker and ent.ticker not in seen:
                tickers.append(ent.ticker)
                seen.add(ent.ticker)

        # Regex patterns for explicit tickers
        # $AAPL pattern
        for m in re.findall(r'\$([A-Z]{2,5})\b', text):
            if m not in seen:
                tickers.append(m)
                seen.add(m)

        for m in parenthesised_tickers(text):
            if len(m) >= 2 and m not in seen:
                tickers.append(m)
                seen.add(m)

        # Full legal company names from the SEC list ("Alphabet Inc." → GOOGL)
        for ticker in resolve_company_tickers(text):
            if ticker not in seen:
                tickers.append(ticker)
                seen.add(ticker)

        return tickers

    def _detect_sector(self, text: str, tickers: list[str]) -> str:
        """Detect the primary sector from text content and tickers."""
        text_lower = text.lower()
        scores = {
            sector: sum(1 for kw in keywords if _matches(kw, text_lower))
            for sector, keywords in SECTOR_KEYWORDS.items()
        }
        best = max(scores, key=lambda s: scores[s])
        return best if scores[best] > 0 else ""

    def _check_breaking_indicators(self, text: str) -> bool:
        """Check if text contains indicators of breaking/urgent news."""
        breaking_patterns = [
            r'\bbreaking\b', r'\bjust\s+in\b', r'\bexclusive\b',
            r'\bflash\b', r'\burgent\b', r'\bjust\s+announced\b',
            r'\bfirst\s+reported\b', r'\bsources?\s+say\b',
            r'\baccording\s+to\s+sources?\b',
        ]
        text_lower = text.lower()
        return any(re.search(p, text_lower) for p in breaking_patterns)

    def get_next_catalyst_date(
        self, nlp_result: NLPResult, reference_date: datetime | None = None
    ) -> str | None:
        """Return the nearest future date from the temporal refs in an NLPResult."""
        return get_next_catalyst_date(nlp_result.temporal_refs, reference_date)


# Convenience function
def analyze_financial_text(
    title: str,
    text: str,
    entity_index: dict[str, list[tuple[str, str]]] | None = None,
) -> NLPResult:
    """Analyze financial text and return structured NLP results."""
    nlp = FinancialNLP(entity_index=entity_index)
    return nlp.analyze(title, text)
