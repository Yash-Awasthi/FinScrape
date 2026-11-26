"""One entity index: company names, aliases and products -> tickers.

Four resolvers existed and every caller picked a subset: `entity_map.resolve_tickers`
for sector keywords, `entity_map.resolve_company_tickers` for SEC legal names,
`ticker_map.resolve_company_tickers` for short names, and nothing for products. A
headline that names a company or a product therefore resolved fewer symbols than the
data already supported. This module merges them into one call, tagged with the source
that produced each pair:

  - keyword        `entity_index.json` sector/region keys (via `entity_map._forward`)
  - product        the plain keys listed in `PRODUCT_KEYS`, added to the same file
  - company-alias  `ticker_map.COMPANY_TO_TICKER` short names ("apple", "tsmc")
  - legal-name     SEC `company_tickers.json` full names (via `entity_map._company_names`)

Matching is `entity_map._matches` (word boundary for a single token, substring for a
phrase) and entity_map's compiled legal-name regex for the 10k-name list; none of it is
re-implemented here. Pure and data-driven: no network, no DB. Imports `entity_map` and
`ticker_map`, never the reverse, so there is no cycle.

Sector keywords are liquid proxies, not investment advice: a geopolitics headline that
names no company still resolves the symbols the sector trades through.
"""

from __future__ import annotations

import functools

from finscrape.analysis.ticker_map import COMPANY_TO_TICKER
from finscrape.extract import entity_map

# Plain `entity_index.json` keys that name a product rather than a sector. Kept in code
# so `entity_map._forward` stays the one loader; every key must exist in the JSON (the
# test asserts this) and every key is unambiguous in market copy.
PRODUCT_KEYS: frozenset[str] = frozenset(
    {
        "iphone",
        "ipad",
        "macbook",
        "airpods",
        "icloud",
        "apple watch",
        "azure",
        "office 365",
        "microsoft 365",
        "xbox",
        "linkedin",
        "github",
        "h100",
        "a100",
        "geforce",
        "tegra",
        "cuda",
        "ryzen",
        "radeon",
        "epyc",
        "prime video",
        "aws",
        "model 3",
        "cybertruck",
        "youtube",
        "gmail",
        "waymo",
        "instagram",
        "whatsapp",
        "oculus",
        "playstation",
        "737 max",
        "dreamliner",
        "f-35",
    }
)

SOURCES: frozenset[str] = frozenset(
    {"keyword", "company-alias", "legal-name", "product"}
)


@functools.lru_cache(maxsize=1)
def _keywords_and_products() -> tuple[
    dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]
]:
    """Split the one loaded keyword map by whether the key names a product."""
    keywords: dict[str, tuple[str, ...]] = {}
    products: dict[str, tuple[str, ...]] = {}
    for key, tickers in entity_map._forward().items():
        (products if key in PRODUCT_KEYS else keywords)[key] = tickers
    return keywords, products


def resolve_detailed(text: str) -> list[tuple[str, str]]:
    """Every (symbol, source) pair the index supports for `text`.

    Source is one of `SOURCES`. A symbol can appear more than once with different
    sources ("apple iphone" -> AAPL/company-alias and AAPL/product); callers that only
    need symbols use `resolve`, callers auditing a resolution read this.
    """
    text_lower = (text or "").lower()
    if not text_lower:
        return []
    keywords, products = _keywords_and_products()
    found: set[tuple[str, str]] = set()
    for key, tickers in keywords.items():
        if entity_map._matches(key, text_lower):
            found.update((ticker, "keyword") for ticker in tickers)
    for key, tickers in products.items():
        if entity_map._matches(key, text_lower):
            found.update((ticker, "product") for ticker in tickers)
    for name, ticker in COMPANY_TO_TICKER.items():
        if entity_map._matches(name, text_lower):
            found.add((ticker.upper(), "company-alias"))
    names = entity_map._company_names()
    legal_rx = entity_map._company_regex()
    if legal_rx is not None:
        found.update(
            (names[m.group(0)], "legal-name") for m in legal_rx.finditer(text_lower)
        )
    return sorted(found)


def resolve(text: str) -> list[str]:
    """Sorted unique tickers the index supports for `text`."""
    return sorted({symbol for symbol, _ in resolve_detailed(text)})
