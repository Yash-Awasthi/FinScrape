"""Stage-1 data: public financial-news headlines mapped onto WorldFin's sector and
direction questions, for one full fine-tune before the daily LoRA runs.

    python scripts/laya_train/build_pretrain.py OUT.json [--per-sector 2500] [--max-rows N]

Sources (all public):
- FNSPID (Zihan1004/FNSPID): S&P 500 news headlines with the stock's ticker; the
  ticker's GICS sector from datasets/s-and-p-500-companies becomes the label. The
  5.7 GB CSV is streamed and abandoned once every sector has its quota.
- zeroshot/twitter-financial-news-topic: topics that name a sector.
- zeroshot/twitter-financial-news-sentiment: bearish/bullish/neutral for direction.
Headlines already in the gold or holdout sets are dropped.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FNSPID = "https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_news/All_external.csv"
SP500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
HF_PARQUET = (
    "https://huggingface.co/api/datasets/zeroshot/{}/parquet/default/train/0.parquet"
)

GICS = {
    "Information Technology": "technology",
    "Communication Services": "communications",
    "Consumer Discretionary": "consumer",
    "Consumer Staples": "consumer",
    "Health Care": "healthcare",
    "Financials": "financials",
    "Energy": "energy",
    "Industrials": "industrials",
    "Materials": "materials",
    "Utilities": "utilities",
    "Real Estate": "real_estate",
}
# twitter-financial-news-topic label ids that name one of our sectors.
TOPIC = {
    1: "financials",
    3: "financials",
    6: "energy",
    8: "financials",
    10: "materials",
    16: "other",
}
SENTIMENT = {0: "negative", 1: "positive", 2: "neutral"}
UP, FLAT = 0.02, 0.005  # abnormal move over the publication day
# Rating and target changes say their own direction; the day's price move mostly
# reflects whatever else happened (earnings, the market).
_MOVER = r"\b(?:shares|stock|profit|earnings|revenue|sales|income)\b[^.;:]{0,25}?"
SAYS_UP = re.compile(
    r"\bupgrades?\b|\braises? (?:price target|pt|guidance|outlook|dividend)\b|\bbeats?\b.*\best"
    r"|trading higher|\bshares (?:are )?up\b|"
    + _MOVER
    + r"\b(?:rises?|jumps?|surges?|climbs?|gains?|soars?|rallies|spikes?|higher)\b",
    re.IGNORECASE,
)
SAYS_DOWN = re.compile(
    r"\bdowngrades?\b|\b(?:lowers?|cuts?) (?:price target|pt|guidance|outlook|dividend)\b"
    r"|\bmiss(?:es)?\b|trading lower|\bshares (?:are )?down\b|"
    + _MOVER
    + r"\b(?:falls?|drops?|slides?|sinks?|tumbles?|plunges?|slumps?|declines?|lower)\b",
    re.IGNORECASE,
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def excluded() -> set[str]:
    out = set()
    home = Path(os.environ.get("LAYA_FT_HOME", Path.home() / "laya-ft"))
    for p in (
        ROOT / "tests" / "fixtures" / "sector_gold.json",
        home / "data" / "holdout.json",
    ):
        if p.exists():
            out |= {
                norm(c["subject"]) for c in json.loads(p.read_text("utf-8"))["cases"]
            }
    return out


def fnspid(per_sector: int, max_rows: int, skip: set[str]) -> list[dict]:
    sp = pd.read_csv(SP500)
    sector_of = {r.Symbol: GICS[r._3] for r in sp.itertuples() if r._3 in GICS}
    name_of = {r.Symbol: r.Security for r in sp.itertuples()}
    counts: Counter[str] = Counter()
    cases, seen = [], set()
    csv.field_size_limit(2**31 - 1)
    with requests.get(FNSPID, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        rows = csv.DictReader(
            io.TextIOWrapper(resp.raw, encoding="utf-8", errors="replace")
        )
        for i, row in enumerate(rows):
            if i % 50000 == 0:
                print(f"  fnspid row {i}: {dict(counts)}", flush=True)
            title = (row.get("Article_title") or "").strip()
            ticker = (row.get("Stock_symbol") or "").upper()
            sector = sector_of.get(ticker)
            n = norm(title)
            if (
                not sector
                or not names_company(title, ticker, name_of.get(ticker, ""))
                or len(n) < 15
                or n in seen
                or n in skip
                or counts[sector] >= per_sector
            ):
                continue
            seen.add(n)
            counts[sector] += 1
            cases.append(
                {
                    "subject": title,
                    "sector": sector,
                    "source": "fnspid",
                    "_ticker": ticker,
                    "_date": (row.get("Date") or "")[:10],
                }
            )
            if i >= max_rows or all(
                counts[s] >= per_sector for s in set(sector_of.values())
            ):
                break
    print("fnspid:", dict(counts), flush=True)
    return market_direction(cases)


def names_company(title: str, ticker: str, name: str) -> bool:
    """True when the headline names the company it is filed under. Market-wide lists
    ("Stocks That Hit 52-Week Highs") are filed under an arbitrary ticker."""
    first = re.sub(r"[^\w]", "", name.split(" ")[0]).lower()
    return (len(first) > 2 and first in title.lower()) or (
        len(ticker) > 1 and bool(re.search(rf"\b{re.escape(ticker)}\b", title))
    )


def market_direction(cases: list[dict]) -> list[dict]:
    """Label FNSPID headlines with the stock's move over the publication day, net of
    SPY: above +UP positive, below -UP negative, inside FLAT neutral, else unlabelled."""
    import yfinance as yf

    # A day with several stories on one stock (earnings plus analyst notes) cannot say
    # which of them moved it, so only a stock's lone story that day is labelled.
    per_day = Counter((c["_ticker"], c["_date"]) for c in cases)
    todo = []
    for c in cases:
        up, down = SAYS_UP.search(c["subject"]), SAYS_DOWN.search(c["subject"])
        if bool(up) != bool(down):
            c["direction"] = "positive" if up else "negative"
        elif not up and c["_date"] and per_day[c["_ticker"], c["_date"]] == 1:
            todo.append(c)
    if todo:
        dates = pd.to_datetime([c["_date"] for c in todo])
        close = yf.download(
            sorted({c["_ticker"] for c in todo} | {"SPY"}),
            start=dates.min() - pd.Timedelta(days=7),
            end=dates.max() + pd.Timedelta(days=7),
            auto_adjust=True,
            progress=False,
        )["Close"]
        for c, day in zip(todo, dates):
            # Last close before the day to the first close after it: whole-day news
            # effect whatever hour the story ran.
            before, after = (
                close.index[close.index < day],
                close.index[close.index > day],
            )
            if c["_ticker"] not in close or not len(before) or not len(after):
                continue
            a, b = close.loc[before[-1]], close.loc[after[0]]
            move = b[c["_ticker"]] / a[c["_ticker"]] - b["SPY"] / a["SPY"]
            if pd.isna(move):  # no price that day
                continue
            if abs(move) >= UP:
                c["direction"] = "positive" if move > 0 else "negative"
            elif abs(move) <= FLAT:
                c["direction"] = "neutral"
            if "direction" in c:
                c["source"] = "fnspid-price"  # weak label; train.py down-weights it
    for c in cases:
        c.pop("_ticker", None)
        c.pop("_date", None)
    print(
        "fnspid market direction:",
        dict(Counter(c.get("direction") for c in cases)),
        flush=True,
    )
    return cases


def twitter(
    name: str, column: str, mapping: dict[int, str], skip: set[str]
) -> list[dict]:
    df = pd.read_parquet(
        io.BytesIO(requests.get(HF_PARQUET.format(name), timeout=60).content)
    )
    cases = []
    for text, label in zip(df["text"], df["label"]):
        text = re.sub(r"https?://\S+", "", str(text)).strip()
        if int(label) in mapping and norm(text) not in skip and len(norm(text)) >= 15:
            cases.append({"subject": text, column: mapping[int(label)], "source": name})
    print(f"{name}: {len(cases)}", flush=True)
    return cases


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--per-sector", type=int, default=2500)
    ap.add_argument("--max-rows", type=int, default=3_000_000)
    # Teacher-labelled files (e.g. data/train.json) to fold in; never the holdout.
    ap.add_argument("--extra", type=Path, nargs="*", default=[])
    args = ap.parse_args()
    skip = excluded()
    cases = (
        twitter("twitter-financial-news-topic", "sector", TOPIC, skip)
        + twitter("twitter-financial-news-sentiment", "direction", SENTIMENT, skip)
        + fnspid(args.per_sector, args.max_rows, skip)
    )
    for path in args.extra:
        extra = [
            c
            for c in json.loads(path.read_text("utf-8"))["cases"]
            if norm(c["subject"]) not in skip
        ]
        cases += [c | {"source": c.get("source") or path.stem} for c in extra]
        print(f"{path.name}: {len(extra)}", flush=True)
    # Most direction rows are neutral; drop neutral direction labels beyond the larger
    # move class so the model is not taught that nothing moves prices.
    moves = Counter(c.get("direction") for c in cases)
    neutral = [c for c in cases if c.get("direction") == "neutral"]
    random.Random(0).shuffle(neutral)
    for c in neutral[max(moves["positive"], moves["negative"]) :]:
        del c["direction"]
    cases = [c for c in cases if c.get("sector") or c.get("direction")]
    print("direction:", dict(Counter(c.get("direction") for c in cases)), flush=True)
    args.out.write_text(json.dumps({"cases": cases}, ensure_ascii=False), "utf-8")
    print(len(cases), "cases ->", args.out)


if __name__ == "__main__":
    sys.exit(main())
