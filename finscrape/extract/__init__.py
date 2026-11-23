"""Extraction: text -> grounded symbols and entities (plan M3.4).

`entity_map` resolves company names from the SEC list and lede-level sector words; the
NLP half stays in `finscrape/analysis/nlp.py` because it is a spaCy pipeline, not an
entity list.
"""

from finscrape.extract.entity_map import (
    keywords_for_ticker,
    lede_tickers,
    resolve_company_tickers,
    resolve_tickers,
    tickers_for_keyword,
)

__all__ = [
    "keywords_for_ticker",
    "lede_tickers",
    "resolve_company_tickers",
    "resolve_tickers",
    "tickers_for_keyword",
]
