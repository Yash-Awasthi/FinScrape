"""
Temporal extraction module for the financial NLP pipeline.

Parses dates, quarters, fiscal years, and time references from unstructured
financial text. Combines regex patterns with spaCy DATE entities for robust
extraction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

ORDINAL_QUARTERS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
}

# Last day of each quarter
QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
QUARTER_START = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}


@dataclass
class TemporalReference:
    """A temporal reference extracted from financial text."""
    raw_text: str
    ref_type: str  # "date", "quarter", "fiscal_year", "relative", "earnings", "deadline"
    resolved_date: str | None = None  # ISO format, e.g. "2026-03-31"
    quarter: str | None = None  # e.g. "Q1 2026"
    fiscal_year: int | None = None  # e.g. 2026
    context: str = ""  # surrounding text for disambiguation


class TemporalExtractor:
    """
    Extracts temporal references from financial text using regex patterns
    and spaCy DATE entities.
    """

    # --- Regex patterns ---

    # Explicit dates: "March 15, 2026" / "Mar 15, 2026"
    _RE_MONTH_DAY_YEAR = re.compile(
        r'\b(' + '|'.join(MONTH_NAMES.keys()) + r')\s+(\d{1,2}),?\s+(\d{4})\b',
        re.IGNORECASE,
    )

    # ISO dates: "2026-03-15"
    _RE_ISO_DATE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')

    # Slash dates: "15/03/2026" or "03/15/2026"
    _RE_SLASH_DATE = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b')

    # Quarters: "Q1 2026", "Q1'26", "Q1 '26"
    _RE_QUARTER_Q = re.compile(
        r"\bQ([1-4])\s*['\u2018\u2019]?\s*(\d{4}|\d{2})\b", re.IGNORECASE,
    )

    # Quarters: "1Q26", "1Q2026"
    _RE_QUARTER_NQ = re.compile(
        r"\b([1-4])Q\s*['\u2018\u2019]?\s*(\d{4}|\d{2})\b", re.IGNORECASE,
    )

    # Quarters: "first quarter 2026", "third quarter of 2026"
    _RE_QUARTER_ORDINAL = re.compile(
        r'\b(' + '|'.join(ORDINAL_QUARTERS.keys()) + r')\s+quarter\s+(?:of\s+)?(\d{4}|\d{2})\b',
        re.IGNORECASE,
    )

    # Fiscal years: "FY2026", "FY26", "FY 2026", "FY 26"
    _RE_FISCAL_YEAR = re.compile(
        r"\bFY\s*['\u2018\u2019]?\s*(\d{4}|\d{2})\b", re.IGNORECASE,
    )

    # Fiscal year long form: "fiscal year 2026"
    _RE_FISCAL_YEAR_LONG = re.compile(
        r'\bfiscal\s+year\s+(\d{4}|\d{2})\b', re.IGNORECASE,
    )

    # Relative date patterns
    _RE_RELATIVE = re.compile(
        r'\b(next\s+quarter|last\s+quarter|next\s+week|last\s+week|'
        r'next\s+month|last\s+month|next\s+year|last\s+year|'
        r'yesterday|today|tomorrow|'
        r'this\s+month|this\s+week|this\s+quarter|this\s+year|'
        r'year[- ]over[- ]year|quarter[- ]over[- ]quarter|'
        r'month[- ]over[- ]month)\b',
        re.IGNORECASE,
    )

    # Earnings references
    _RE_EARNINGS = re.compile(
        r'\b(earnings\s+call\s+on\s+\w[\w\s,]*|'
        r'reports?\s+(?:earnings\s+)?on\s+\w[\w\s,]*|'
        r'next\s+earnings|'
        r'earnings\s+(?:release|report|announcement|date|season)|'
        r'(?:quarterly|annual)\s+earnings)\b',
        re.IGNORECASE,
    )

    # Deadlines
    _RE_DEADLINE = re.compile(
        r'\b(deadline(?:\s+(?:is|of|on|for)\s+\w[\w\s,]*)?|'
        r'due\s+date(?:\s+(?:is|of|on|for)\s+\w[\w\s,]*)?|'
        r'expires?\s+(?:on\s+)?\w[\w\s,]*|'
        r'by\s+end\s+of\s+\w[\w\s,]*)\b',
        re.IGNORECASE,
    )

    def _normalize_year(self, y: str) -> int:
        """Normalize a 2- or 4-digit year string to a 4-digit int."""
        val = int(y)
        if val < 100:
            val += 2000
        return val

    def _get_context(self, text: str, start: int, end: int, window: int = 40) -> str:
        """Return surrounding text for a match span."""
        ctx_start = max(0, start - window)
        ctx_end = min(len(text), end + window)
        return text[ctx_start:ctx_end].strip()

    def _resolve_quarter_date(self, q: int, year: int) -> str:
        """Return the end-of-quarter date in ISO format."""
        month, day = QUARTER_END[q]
        return f"{year:04d}-{month:02d}-{day:02d}"

    def extract(
        self,
        text: str,
        reference_date: datetime | None = None,
        doc=None,
    ) -> list[TemporalReference]:
        """
        Extract all temporal references from the given text.

        Args:
            text: The financial text to analyze.
            reference_date: Anchor for resolving relative dates. Defaults to now.
            doc: An already-parsed spaCy doc for this text. Pass this when the
                 caller already ran spaCy NER, to avoid parsing the same text twice.
                 Falls back to parsing `text` itself when not given.

        Returns:
            A deduplicated list of TemporalReference objects.
        """
        if reference_date is None:
            reference_date = datetime.now()

        refs: list[TemporalReference] = []
        seen_spans: set[tuple[int, int]] = set()  # avoid duplicates by span

        def _add(start: int, end: int, ref: TemporalReference):
            key = (start, end)
            if key not in seen_spans:
                seen_spans.add(key)
                refs.append(ref)

        # 1. Explicit dates — "March 15, 2026"
        for m in self._RE_MONTH_DAY_YEAR.finditer(text):
            month_num = MONTH_NAMES.get(m.group(1).lower())
            day = int(m.group(2))
            year = int(m.group(3))
            if month_num and 1 <= day <= 31:
                try:
                    dt = datetime(year, month_num, day)
                    _add(m.start(), m.end(), TemporalReference(
                        raw_text=m.group(0),
                        ref_type="date",
                        resolved_date=dt.strftime("%Y-%m-%d"),
                        context=self._get_context(text, m.start(), m.end()),
                    ))
                except ValueError:
                    pass

        # 2. ISO dates — "2026-03-15"
        for m in self._RE_ISO_DATE.finditer(text):
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                dt = datetime(year, month, day)
                _add(m.start(), m.end(), TemporalReference(
                    raw_text=m.group(0),
                    ref_type="date",
                    resolved_date=dt.strftime("%Y-%m-%d"),
                    context=self._get_context(text, m.start(), m.end()),
                ))
            except ValueError:
                pass

        # 3. Slash dates — "15/03/2026"
        for m in self._RE_SLASH_DATE.finditer(text):
            a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            # Try day/month/year first, then month/day/year
            resolved = None
            for d, mo in [(a, b), (b, a)]:
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    try:
                        dt = datetime(year, mo, d)
                        resolved = dt.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
            if resolved:
                _add(m.start(), m.end(), TemporalReference(
                    raw_text=m.group(0),
                    ref_type="date",
                    resolved_date=resolved,
                    context=self._get_context(text, m.start(), m.end()),
                ))

        # 4. Quarters — "Q1 2026", "Q1'26"
        for m in self._RE_QUARTER_Q.finditer(text):
            q = int(m.group(1))
            year = self._normalize_year(m.group(2))
            _add(m.start(), m.end(), TemporalReference(
                raw_text=m.group(0),
                ref_type="quarter",
                resolved_date=self._resolve_quarter_date(q, year),
                quarter=f"Q{q} {year}",
                fiscal_year=year,
                context=self._get_context(text, m.start(), m.end()),
            ))

        # 5. Quarters — "1Q26"
        for m in self._RE_QUARTER_NQ.finditer(text):
            q = int(m.group(1))
            year = self._normalize_year(m.group(2))
            _add(m.start(), m.end(), TemporalReference(
                raw_text=m.group(0),
                ref_type="quarter",
                resolved_date=self._resolve_quarter_date(q, year),
                quarter=f"Q{q} {year}",
                fiscal_year=year,
                context=self._get_context(text, m.start(), m.end()),
            ))

        # 6. Quarters — "first quarter 2026"
        for m in self._RE_QUARTER_ORDINAL.finditer(text):
            q = ORDINAL_QUARTERS.get(m.group(1).lower())
            if q:
                year = self._normalize_year(m.group(2))
                _add(m.start(), m.end(), TemporalReference(
                    raw_text=m.group(0),
                    ref_type="quarter",
                    resolved_date=self._resolve_quarter_date(q, year),
                    quarter=f"Q{q} {year}",
                    fiscal_year=year,
                    context=self._get_context(text, m.start(), m.end()),
                ))

        # 7. Fiscal years — "FY2026", "FY 26"
        for m in self._RE_FISCAL_YEAR.finditer(text):
            year = self._normalize_year(m.group(1))
            _add(m.start(), m.end(), TemporalReference(
                raw_text=m.group(0),
                ref_type="fiscal_year",
                resolved_date=f"{year}-12-31",
                fiscal_year=year,
                context=self._get_context(text, m.start(), m.end()),
            ))

        # 8. Fiscal years — "fiscal year 2026"
        for m in self._RE_FISCAL_YEAR_LONG.finditer(text):
            year = self._normalize_year(m.group(1))
            _add(m.start(), m.end(), TemporalReference(
                raw_text=m.group(0),
                ref_type="fiscal_year",
                resolved_date=f"{year}-12-31",
                fiscal_year=year,
                context=self._get_context(text, m.start(), m.end()),
            ))

        # 9. Relative dates
        for m in self._RE_RELATIVE.finditer(text):
            raw = m.group(0)
            resolved = self._resolve_relative(raw, reference_date)
            _add(m.start(), m.end(), TemporalReference(
                raw_text=raw,
                ref_type="relative",
                resolved_date=resolved,
                context=self._get_context(text, m.start(), m.end()),
            ))

        # 10. Earnings references
        for m in self._RE_EARNINGS.finditer(text):
            _add(m.start(), m.end(), TemporalReference(
                raw_text=m.group(0),
                ref_type="earnings",
                context=self._get_context(text, m.start(), m.end()),
            ))

        # 11. Deadlines
        for m in self._RE_DEADLINE.finditer(text):
            _add(m.start(), m.end(), TemporalReference(
                raw_text=m.group(0),
                ref_type="deadline",
                context=self._get_context(text, m.start(), m.end()),
            ))

        # 12. Supplement with spaCy DATE entities (non-overlapping only)
        if doc is None:
            from finscrape.analysis.nlp import _get_nlp
            nlp = _get_nlp()
            if nlp:
                doc = nlp(text[:10000])
        if doc is not None:
            for ent in doc.ents:
                if ent.label_ == "DATE":
                    # Skip if overlaps with any already-seen span
                    overlaps = any(
                        not (ent.end_char <= s or ent.start_char >= e)
                        for s, e in seen_spans
                    )
                    if not overlaps:
                        _add(ent.start_char, ent.end_char, TemporalReference(
                            raw_text=ent.text,
                            ref_type="date",
                            context=self._get_context(text, ent.start_char, ent.end_char),
                        ))

        return refs

    def _resolve_relative(self, raw: str, ref: datetime) -> str | None:
        """Resolve a relative time expression to an ISO date string."""
        lower = raw.lower().strip()
        # Normalize hyphens
        lower = lower.replace("-", " ").replace("–", " ")

        if lower == "yesterday":
            return (ref - timedelta(days=1)).strftime("%Y-%m-%d")
        if lower == "today":
            return ref.strftime("%Y-%m-%d")
        if lower == "tomorrow":
            return (ref + timedelta(days=1)).strftime("%Y-%m-%d")

        if lower == "next week":
            return (ref + timedelta(weeks=1)).strftime("%Y-%m-%d")
        if lower == "last week":
            return (ref - timedelta(weeks=1)).strftime("%Y-%m-%d")
        if lower == "this week":
            return ref.strftime("%Y-%m-%d")

        if lower == "next month":
            # First day of next month
            if ref.month == 12:
                return datetime(ref.year + 1, 1, 1).strftime("%Y-%m-%d")
            return datetime(ref.year, ref.month + 1, 1).strftime("%Y-%m-%d")
        if lower == "last month":
            if ref.month == 1:
                return datetime(ref.year - 1, 12, 1).strftime("%Y-%m-%d")
            return datetime(ref.year, ref.month - 1, 1).strftime("%Y-%m-%d")
        if lower == "this month":
            return ref.strftime("%Y-%m-%d")

        if lower == "next year":
            return datetime(ref.year + 1, 1, 1).strftime("%Y-%m-%d")
        if lower == "last year":
            return datetime(ref.year - 1, 1, 1).strftime("%Y-%m-%d")
        if lower == "this year":
            return ref.strftime("%Y-%m-%d")

        # Quarter-relative
        current_q = (ref.month - 1) // 3 + 1
        if lower == "next quarter":
            nq = current_q + 1
            ny = ref.year
            if nq > 4:
                nq = 1
                ny += 1
            return self._resolve_quarter_date(nq, ny)
        if lower == "last quarter":
            pq = current_q - 1
            py = ref.year
            if pq < 1:
                pq = 4
                py -= 1
            return self._resolve_quarter_date(pq, py)
        if lower == "this quarter":
            return self._resolve_quarter_date(current_q, ref.year)

        # Comparison patterns — no single resolved date
        if "over" in lower:
            return None

        return None


def get_next_catalyst_date(
    temporal_refs: list[TemporalReference],
    reference_date: datetime | None = None,
) -> str | None:
    """
    Return the nearest future resolved date from a list of temporal references.

    Useful for identifying the next catalyst / event date for a stock.
    """
    if reference_date is None:
        reference_date = datetime.now()

    ref_str = reference_date.strftime("%Y-%m-%d")
    future_dates: list[str] = []

    for tr in temporal_refs:
        if tr.resolved_date and tr.resolved_date > ref_str:
            future_dates.append(tr.resolved_date)

    if not future_dates:
        return None

    future_dates.sort()
    return future_dates[0]
