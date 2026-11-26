"""Which layer of the sector chain decided, mirrored from `laya.choose_sector`.

The chain is replayed here in the same order and with the same predicates, and
the winner is named:

1. ``laya``      a Laya label at or above ``CONFIDENT`` with no company named;
2. ``model``     the LLM token, but only after the technology guard;
3. ``keyword``   the keyword detector's label;
4. ``company``   the sector of the one company named, ties rejected;
5. ``fallback``  a Laya label at or above the floor, else ``"other"``.

That order is the attribution, not a parallel scoring scheme: a decision is only
``model`` when the LLM's "technology" had keyword or company support, because a
cleared token never reaches the chain.

Offline there are no recorded LLM sector labels, so model-layer accuracy is
UNPROVABLE; only the number of ``model`` decisions is measurable, and only when
the caller passes an ``llm_sector`` in.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from finscrape.analysis import sp500

# The private floor is imported so this attribution cannot drift from the real chain.
from finscrape.analysis.laya import _FLOOR, CONFIDENT, LayaView
from finscrape.analysis.sectors import TAXONOMY, normalize
from finscrape.analysis.ticker_map import TICKER_SECTOR

DECIDERS = ("laya", "model", "keyword", "company", "fallback")


def company_counts(tickers: Iterable[str]) -> Counter[str]:
    """Sector tally of the named companies, the curated map before the S&P 500 table."""
    return Counter(s for t in tickers if (s := TICKER_SECTOR.get(t) or sp500.sector(t)))


def company_sector(tickers: Iterable[str]) -> str:
    """Sector of the single most-named company; "" on no sector or a tie."""
    top = company_counts(tickers).most_common(2)
    return top[0][0] if top and (len(top) == 1 or top[0][1] > top[1][1]) else ""


def decide(
    llm_sector: str,
    view: LayaView | None,
    keyword_sector: str,
    tickers: Iterable[str] = (),
) -> dict[str, str]:
    """The sector `laya.choose_sector` would pick, plus the layer that picked it."""
    tickers = tuple(tickers)
    laya_p = view.sector_p if view and view.sector in TAXONOMY else 0.0
    company = company_counts(tickers)
    # On headlines naming a company the company evidence outranks Laya, as in the chain.
    if laya_p >= CONFIDENT and not company:
        return {
            "sector": view.sector,  # type: ignore[union-attr]
            "decided_by": "laya",
            "detail": f"laya {laya_p:.2f} >= {CONFIDENT:.2f} and no company named",
        }
    llm = next((s for s in normalize(llm_sector) if s in TAXONOMY and s != "other"), "")
    cleared = (
        llm == "technology"
        and keyword_sector != "technology"
        and "technology" not in company
    )
    if cleared:
        llm = ""
    if llm:
        return {"sector": llm, "decided_by": "model", "detail": f"llm said {llm}"}
    if keyword_sector:
        detail = f"keyword {keyword_sector}"
        if cleared:
            detail += " (llm technology had no keyword or company support)"
        return {"sector": keyword_sector, "decided_by": "keyword", "detail": detail}
    named = company_sector(tickers)
    if named:
        return {"sector": named, "decided_by": "company", "detail": f"company {named}"}
    fallback = view.sector if view and laya_p >= _FLOOR else "other"
    return {
        "sector": fallback,
        "decided_by": "fallback",
        "detail": f"no usable llm; laya {laya_p:.2f} -> {fallback}",
    }
