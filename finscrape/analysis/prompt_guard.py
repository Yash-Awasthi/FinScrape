"""Hallucination guard: a verdict may only name symbols the article backs.

`validator.grounded_tickers` filters what the LLM returned for one article; this
answers the same question for a finished verdict with no LLM in the loop. The only
admissible sources are the article text, the merged entity index and the LLM's own
named entities. Pure: the index is the data entity_map already loads.
"""

from __future__ import annotations

import re

from finscrape.analysis.validator import clean_tickers, grounded_tickers
from finscrape.extract import entity_index
from finscrape.extract.entity_map import parenthesised_tickers

# Explicit trader shorthand; entity_map reads "(TICK)" and rejects acronyms and
# unlisted agencies.
_CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
# A bare symbol is uppercase by convention. A case-insensitive scan would ground ARM
# from "arm wrestlers" and TGT from "price target"; this stays case-sensitive.
_BARE_SYMBOL = re.compile(r"(?<![A-Za-z0-9$])([A-Z]{1,5})(?![A-Za-z0-9])")


def _text_tickers(text: str) -> set[str]:
    """Symbols the article spells explicitly, stopwords filtered by clean_tickers."""
    found = {m.upper() for m in _CASHTAG.findall(text)}
    found.update(parenthesised_tickers(text))
    found.update(_BARE_SYMBOL.findall(text))
    return set(clean_tickers(sorted(found), text))


def _backed(tickers: list[str], text: str, entities: list[dict]) -> set[str]:
    backed = set(entity_index.resolve(text))
    backed.update(_text_tickers(text))
    # Same rule the pipeline already uses: an LLM-named entity counts only when its
    # name is in the text and its ticker agrees with the curated map/SEC title.
    backed.update(grounded_tickers(tickers, entities, [], text))
    return backed


def ungrounded_tickers(
    tickers: list[str], text: str, entities: list[dict] | None = None
) -> list[str]:
    """Every ticker no source backs, in input order, deduplicated."""
    wanted = list(dict.fromkeys(tickers))
    backed = _backed(wanted, text or "", entities or [])
    return [t for t in wanted if t.upper() not in backed]


def assert_grounded(
    tickers: list[str], text: str, entities: list[dict] | None = None
) -> list[str]:
    """Return the grounded verdict, or raise ValueError naming every offender."""
    grounded = list(dict.fromkeys(tickers))
    offenders = ungrounded_tickers(grounded, text, entities)
    if offenders:
        raise ValueError(
            "ungrounded tickers (not in article text or entity index): "
            + ", ".join(offenders)
        )
    return grounded
