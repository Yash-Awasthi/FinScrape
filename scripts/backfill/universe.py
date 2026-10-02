"""Build data/backfill/universe.parquet and prices.parquet: `python -m scripts.backfill.universe`.

Universe is today's S&P 500 from Wikipedia (survivorship bias accepted, docs/LAYA_PLAN.md);
prices are 3 years of adjusted daily closes from yfinance, SPY included.
"""

from __future__ import annotations

import io
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import requests

from finscrape.analysis.ticker_map import COMPANY_TO_TICKER

OUT = Path("data/backfill")
WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
GICS = {
    "Information Technology": "technology",
    "Health Care": "healthcare",
    "Financials": "financials",
    "Energy": "energy",
    "Consumer Discretionary": "consumer",
    "Consumer Staples": "consumer",
    "Industrials": "industrials",
    "Materials": "materials",
    "Utilities": "utilities",
    "Real Estate": "real_estate",
    "Communication Services": "communications",
}
SUFFIXES = {
    "inc",
    "incorporated",
    "corporation",
    "corp",
    "company",
    "co",
    "plc",
    "ltd",
    "the",
}
# Single words that mostly mean something else in a headline; fuller names still match.
AMBIGUOUS = {
    "apa",
    "aes",
    "ball",
    "best",
    "block",
    "booking",
    "carnival",
    "coherent",
    "dover",
    "dow",
    "everest",
    "flex",
    "gap",
    "general",
    "global",
    "hartford",
    "match",
    "mosaic",
    "news",
    "progressive",
    "public",
    "target",
    "ups",
    "visa",
    "waters",
}


def norm(text: str) -> str:
    """Lowercase ASCII words, the shape `slug_title` leaves after its hyphens are split."""
    plain = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.lower()).split())


def short_name(security: str) -> str:
    """'Alphabet Inc. (Class A)' -> 'alphabet'; 'The Home Depot' -> 'home depot'."""
    words = norm(re.sub(r"\(.*?\)", " ", security)).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words[1:] if words[:1] == ["the"] else words)


def build_universe(table: pd.DataFrame) -> pd.DataFrame:
    curated: dict[str, set[str]] = {}
    for name, ticker in COMPANY_TO_TICKER.items():
        curated.setdefault(ticker, set()).add(norm(name))
    rows, seen = [], set()
    for sym, sec, gics in table[["Symbol", "Security", "GICS Sector"]].itertuples(
        index=False
    ):
        ticker = sym.replace(".", "-")
        name = short_name(sec)
        if name in AMBIGUOUS:
            name = norm(re.sub(r"\(.*?\)", " ", sec))  # 'news corp', 'dow inc'
        aliases = curated.get(ticker, set())
        # A second share class (GOOG, NWS) gets no name, so one company stays one match.
        if name not in seen:
            aliases = aliases | {name}
        seen.add(name)
        keep = sorted(a for a in aliases if len(a) >= 3 and a not in AMBIGUOUS)
        rows.append((ticker, sec, gics, GICS[gics], keep))
    return pd.DataFrame(
        rows, columns=["ticker", "name", "gics_sector", "sector", "aliases"]
    )


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        tickers, period="3y", auto_adjust=True, progress=False, threads=True
    )
    close = raw["Close"].dropna(how="all")
    # Today's bar is intraday until the close; the next run picks it up.
    close = close[
        close.index < pd.Timestamp.now("America/New_York").normalize().tz_localize(None)
    ]
    out = close.stack().dropna().rename("close").reset_index()
    out.columns = ["date", "ticker", "close"]
    return out


def check(uni: pd.DataFrame, prices: pd.DataFrame) -> list[str]:
    """Tickers missing over 5% of trading days since their first close; later listings are
    reported, not failed, since those days never traded."""
    days = pd.Index(sorted(prices["date"].unique()))
    span = prices.groupby("ticker")["date"].agg(["min", "count"])
    span = span.reindex(uni["ticker"].tolist() + ["SPY"])
    listed = span["min"].map(lambda d: (days >= d).sum() if pd.notna(d) else len(days))
    missing = 1 - span["count"].fillna(0) / listed
    bad = missing[missing > 0.05]
    late = span[span["min"] > days[0]]
    print(
        f"tickers {len(uni)}, unmapped {uni['sector'].isna().sum()}, days {len(days)}"
    )
    print(f"no aliases: {list(uni.loc[uni['aliases'].str.len() == 0, 'ticker'])}")
    print(f"listed later: {len(late)} {late['min'].dt.date.astype(str).to_dict()}")
    print(f"over 5% days missing: {len(bad)} {bad.round(3).to_dict()}")
    return list(bad.index)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    html = requests.get(
        WIKI, headers={"User-Agent": "worldfin-backfill"}, timeout=30
    ).text
    uni = build_universe(
        pd.read_html(io.StringIO(html), attrs={"id": "constituents"})[0]
    )
    uni.to_parquet(OUT / "universe.parquet", index=False)
    prices = fetch_prices(uni["ticker"].tolist() + ["SPY"])
    prices.to_parquet(OUT / "prices.parquet", index=False)
    return 1 if check(uni, prices) else 0


if __name__ == "__main__":
    sys.exit(main())
