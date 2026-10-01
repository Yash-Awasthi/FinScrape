"""Collect fresh headlines for Laya's teacher to label, from every source WorldFin reads
plus Firecrawl news search, deduplicated against all existing Laya data.

    .venv/Scripts/python scripts/laya_train/collect_news.py OUT.json [--days 30] [--no-firecrawl]

Sources: production events in Postgres, the worker's world RSS and event ingestors, the
market scrapers in finscrape.scrapers, and `firecrawl search --sources news` per theme.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import daily as d
from dotenv import dotenv_values

MARKET_SCRAPERS = (
    "yahoo", "cnbc", "reuters", "marketwatch", "benzinga", "google_news",
    "investingcom", "seekingalpha", "ft", "bloomberg",
)  # fmt: skip
THEMES = (
    "oil prices OPEC crude", "natural gas LNG prices", "central bank interest rates",
    "bank earnings lending", "stock market selloff", "stock market rally",
    "semiconductor chips export controls", "big tech earnings", "AI data center spending",
    "pharmaceutical drug approval FDA", "hospital insurers healthcare costs",
    "retail sales consumer spending", "automakers tariffs", "airlines airfare demand",
    "defense contracts military spending", "shipping freight rates Red Sea",
    "copper iron ore mining", "gold price", "steel aluminium tariffs",
    "electric utilities power prices", "real estate housing market mortgage",
    "telecom wireless carriers", "media streaming advertising", "sanctions Russia exports",
    "China economy stimulus", "India economy markets", "Middle East conflict markets",
    "crypto bitcoin regulation", "food prices agriculture wheat", "layoffs job cuts",
)  # fmt: skip


async def db_subjects(days: int) -> list[tuple[str, str]]:
    import asyncpg

    conn = await asyncpg.connect(dotenv_values(ROOT / ".env")["WORLDFIN_DATABASE_URL"])
    try:
        rows = await conn.fetch(
            "SELECT subject FROM events WHERE created_at >= now() - make_interval(days => $1)",
            days,
        )
    finally:
        await conn.close()
    return [(r["subject"], "prod") for r in rows]


def worker_sources() -> list[tuple[str, str]]:
    from worker.sources import build_sources

    out = []
    for name, produce in build_sources(max_articles=1000).items():
        try:
            out += [(a.title, name) for a, _ in produce()]
        except Exception as exc:  # noqa: BLE001 - one dead feed must not sink the harvest
            print(f"  {name} failed: {exc}", flush=True)
    return out


def market_scrapers() -> list[tuple[str, str]]:
    import importlib

    def run(mod: str) -> list[tuple[str, str]]:
        m = importlib.import_module(f"finscrape.scrapers.{mod}")
        cls = next(
            v
            for k, v in vars(m).items()
            if k.endswith("Scraper") and getattr(v, "name", "") == mod
        )
        try:
            return [(a.title, mod) for a in cls(max_articles=100).scrape_news()]
        except Exception as exc:  # noqa: BLE001
            print(f"  {mod} failed: {exc}", flush=True)
            return []

    with ThreadPoolExecutor(4) as pool:
        return [row for rows in pool.map(run, MARKET_SCRAPERS) for row in rows]


def firecrawl_news(themes=THEMES, tbs: str = "qdr:m") -> list[tuple[str, str]]:
    exe = shutil.which("firecrawl")
    if not exe:
        print("  firecrawl CLI not on PATH", flush=True)
        return []
    out = []
    for q in themes:
        run = subprocess.run(
            [exe, "search", q, "--sources", "news", "--tbs", tbs, "--limit", "100", "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=180, check=False,
        )  # fmt: skip
        try:
            news = json.loads(run.stdout)["data"].get("news") or []
        except (ValueError, KeyError, TypeError):
            news = []
        out += [(n["title"], "firecrawl") for n in news if n.get("title")]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--no-firecrawl", action="store_true")
    # Targeted rounds: only Firecrawl, on these ';'-separated queries (e.g. a weak class).
    ap.add_argument("--themes", default="")
    ap.add_argument("--tbs", default="qdr:m", help="Firecrawl time window, e.g. qdr:y")
    args = ap.parse_args()

    known = {
        d.norm(c["subject"])
        for p in (
            d.DATA / "train.json",
            d.DATA / "holdout.json",
            d.GOLD,
            d.DATA / "pretrain.json",
        )
        for c in d.load(p)
    }
    steps = [("db", lambda: asyncio.run(db_subjects(args.days))), ("worker", worker_sources),
             ("market", market_scrapers)]  # fmt: skip
    if args.themes:
        steps = [
            ("firecrawl", lambda: firecrawl_news(args.themes.split(";"), args.tbs))
        ]
    elif not args.no_firecrawl:
        steps.append(("firecrawl", firecrawl_news))
    rows = []
    for name, step in steps:
        got = step()
        print(f"{name}: {len(got)} headlines", flush=True)
        rows += got

    seen, cases = set(known), []
    for title, source in rows:
        title = re.sub(r"\s+", " ", str(title or "")).strip()
        # Drop the " - Publisher" tail Google News and GDELT append.
        title = re.sub(r" [-|] [A-Z][\w.&' ]{1,40}$", "", title)
        n = d.norm(title)
        if len(n) < 25 or n in seen or d.TEMPLATED.search(title):
            continue
        seen.add(n)
        cases.append({"subject": title, "source": source})
    args.out.write_text(
        json.dumps({"cases": cases}, ensure_ascii=False, indent=1), "utf-8"
    )
    print(
        len(cases),
        "new headlines ->",
        args.out,
        dict(Counter(c["source"] for c in cases)),
    )


if __name__ == "__main__":
    main()
