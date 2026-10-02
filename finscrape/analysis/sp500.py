"""S&P 500 short company names and sectors, for sector evidence only.

`sp500.json` is written by `python -m scripts.backfill.universe` (Wikipedia's constituents,
GICS mapped to the taxonomy). Headlines often name a company by its short name ("netflix"),
which the full legal names in `entity_map` miss. These matches back the sector label and
never become event tickers.
"""

from __future__ import annotations

import functools
import json
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

TABLE = Path(__file__).with_name("sp500.json")


def norm(text: str) -> str:
    """Lowercase ASCII words, the shape `slug_title` leaves after its hyphens are split."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.lower()).split())


def compile_matcher(alias: dict[str, str]) -> Callable[[str], list[str]]:
    """text -> sorted tickers whose alias appears in it as whole words, longest alias first."""
    rx = re.compile(
        r"(?<![a-z0-9])(?:"
        + "|".join(re.escape(a) for a in sorted(alias, key=len, reverse=True))
        + r")(?![a-z0-9])"
    )
    return lambda text: sorted({alias[m.group(0)] for m in rx.finditer(norm(text))})


@functools.lru_cache(maxsize=1)
def _table() -> tuple[dict[str, str], Callable[[str], list[str]]]:
    rows = json.loads(TABLE.read_text("utf-8"))
    alias = {a: t for t, (_, aliases) in rows.items() for a in aliases}
    return {t: s for t, (s, _) in rows.items()}, compile_matcher(alias)


def sector(ticker: str) -> str:
    return _table()[0].get(ticker, "")


def headline_tickers(title: str) -> list[str]:
    return _table()[1](title)
