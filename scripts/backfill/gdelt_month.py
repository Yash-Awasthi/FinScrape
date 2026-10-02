"""One month of GDELT 2.0 event exports as data/backfill/events/YYYY-MM.parquet.

`python -m scripts.backfill.gdelt_month 2026-09` reads the month's 15-minute exports in
memory (nothing raw is kept), keeps one row per URL (most mentions wins) and tags each
with the universe companies its slug title names.
"""

from __future__ import annotations

import csv
import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from finscrape.analysis.sp500 import compile_matcher
from finscrape.ingestors.gdelt import (
    _ADDED,
    _CAMEO,
    _COUNTRY,
    _GOLDSTEIN,
    _ID,
    _LAT,
    _LON,
    _MENTIONS,
    _QUAD,
    _TONE,
    _URL,
    _float,
    slug_title,
)

OUT = Path("data/backfill")
EXPORT = "https://data.gdeltproject.org/gdeltv2/{}.export.CSV.zip"
COLUMNS = [
    "event_id", "added_utc", "url", "domain", "title", "cameo", "quad_class", "goldstein",
    "mentions", "avg_tone", "country", "lat", "lon", "tickers", "n_companies",
]  # fmt: skip


def stamps(month: str) -> list[str]:
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    # The current month stops at the newest export GDELT can have published.
    end = min(
        (start + timedelta(days=32)).replace(day=1),
        datetime.now(UTC) - timedelta(minutes=30),
    )
    out, t = [], start
    while t < end:
        out.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
    return out


def fetch(stamp: str) -> bytes | None:
    """The export's bytes, b"" when GDELT never published it (404), None on failure."""
    for attempt in range(4):
        try:
            resp = requests.get(EXPORT.format(stamp), timeout=60)
            if resp.status_code == 404:
                return b""
            resp.raise_for_status()
            return resp.content
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
    return None


def matcher(universe: pd.DataFrame):
    """title -> sorted tickers whose alias appears in it as whole words."""
    return compile_matcher(
        {
            a: t
            for t, aliases in zip(universe["ticker"], universe["aliases"])
            for a in aliases
        }
    )


_KEEP = (_ID, _ADDED, _URL, _CAMEO, _QUAD, _GOLDSTEIN, _MENTIONS, _TONE, _COUNTRY, _LAT, _LON)  # fmt: skip


def parse_export(data: bytes):
    """Rows trimmed to the kept columns, in `_KEEP` order; a month untrimmed is gigabytes."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    for r in csv.reader(io.StringIO(text), delimiter="	"):
        if len(r) > _URL:
            yield tuple(r[i] for i in _KEEP)


def build(rows, match) -> pd.DataFrame:
    best: dict[str, tuple] = {}
    for r in rows:
        url = r[2]
        if url not in best or int(r[6] or 0) > int(best[url][6] or 0):
            best[url] = r
    out = []
    for url, (eid, added, _, cameo, quad, gold, mentions, tone, country, lat, lon) in best.items():  # fmt: skip
        title = slug_title(url)
        tickers = match(title) if title else []
        out.append(
            (
                int(eid),
                datetime.strptime(added, "%Y%m%d%H%M%S").replace(tzinfo=UTC),
                url,
                urlparse(url).netloc.lower().removeprefix("www."),
                title,
                cameo,
                int(quad or 0),
                _float(gold),
                int(mentions or 0),
                _float(tone),
                country,
                _float(lat),
                _float(lon),
                tickers,
                len(tickers),
            )
        )
    return pd.DataFrame(out, columns=COLUMNS)


def main(month: str) -> int:
    (OUT / "events").mkdir(parents=True, exist_ok=True)
    universe = pd.read_parquet(OUT / "universe.parquet")
    all_stamps = stamps(month)
    t0 = time.time()
    with ThreadPoolExecutor(8) as pool:
        got = list(pool.map(fetch, all_stamps))
    took = time.time() - t0
    failed = [s for s, d in zip(all_stamps, got) if d is None]
    if failed:
        print(f"FAILED {month}: {len(failed)} exports unreachable, first {failed[0]}")
        return 1
    data = [d for d in got if d]
    n_rows = 0

    def rows():
        nonlocal n_rows
        for d in data:
            for r in parse_export(d):
                n_rows += 1
                yield r

    df = build(rows(), matcher(universe))
    path = OUT / "events" / f"{month}.parquet"
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)

    sector = dict(zip(universe["ticker"], universe["sector"]))
    single = df[df["n_companies"] == 1]
    print(
        f"files {len(data)}/{len(all_stamps)} (not published {len(all_stamps) - len(data)})"
    )
    print(f"bytes {sum(map(len, data)):,}, download {took:.0f}s")
    print(
        f"rows {n_rows:,}, events (distinct URLs) {len(df):,}, titled {(df['title'] != '').sum():,}"
    )
    print(
        f"with a company {(df['n_companies'] > 0).sum():,}, single-company {len(single):,}"
    )
    print(single["tickers"].str[0].map(sector).value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
