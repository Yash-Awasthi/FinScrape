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
            sector = sector_of.get((row.get("Stock_symbol") or "").upper())
            n = norm(title)
            if (
                not sector
                or len(n) < 15
                or n in seen
                or n in skip
                or counts[sector] >= per_sector
            ):
                continue
            seen.add(n)
            counts[sector] += 1
            cases.append({"subject": title, "sector": sector, "source": "fnspid"})
            if i >= max_rows or all(
                counts[s] >= per_sector for s in set(sector_of.values())
            ):
                break
    print("fnspid:", dict(counts), flush=True)
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
    if column == "direction":
        # Two in three rows are neutral; cap them at the larger move class.
        by = {d: [c for c in cases if c[column] == d] for d in SENTIMENT.values()}
        cap = max(len(by["positive"]), len(by["negative"]))
        cases = by["positive"] + by["negative"] + by["neutral"][:cap]
    print(f"{name}: {len(cases)}", flush=True)
    return cases


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--per-sector", type=int, default=2500)
    ap.add_argument("--max-rows", type=int, default=3_000_000)
    args = ap.parse_args()
    skip = excluded()
    cases = (
        twitter("twitter-financial-news-topic", "sector", TOPIC, skip)
        + twitter("twitter-financial-news-sentiment", "direction", SENTIMENT, skip)
        + fnspid(args.per_sector, args.max_rows, skip)
    )
    args.out.write_text(json.dumps({"cases": cases}, ensure_ascii=False), "utf-8")
    print(len(cases), "cases ->", args.out)


if __name__ == "__main__":
    sys.exit(main())
