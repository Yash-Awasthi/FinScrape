"""Freeze a dated public sample of 8-K filings as a gold set (plan M5.2).

Source: SEC EDGAR full-text search (https://efts.sec.gov/LATEST/search-index), a US
government work in the public domain, read through the SEC fair-access policy (descriptive
User-Agent, at most 10 requests a second). Two months of form 8-K filings are fetched, the
company's SIC division gives the sector label, and the filing's own date becomes the
period. Verdicts are null: a filing is not a direction call, and a guessed label would be
worse than none. This is a public sample for the walk-forward mechanism, never production.

    python -m scripts.gold_public_sample --write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "gold" / "public_sample_2026_09_10.jsonl"
MANIFEST = ROOT / "tests" / "gold" / "public_sample_2026_09_10.manifest.json"
MONTHS = (("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31"))
PER_MONTH = 40
UA = "FinScrape public-sample test; ops contact in the repository owner profile"

# SIC major group (first two digits) to the product's eleven sectors. The table is the
# label rule; a code that is absent is dropped rather than guessed as "other".
DIVISIONS = {
    "10": "materials",
    "12": "energy",
    "13": "energy",
    "14": "materials",
    "15": "industrials",
    "16": "industrials",
    "17": "industrials",
    "20": "consumer",
    "21": "consumer",
    "22": "consumer",
    "23": "consumer",
    "24": "consumer",
    "25": "consumer",
    "26": "materials",
    "27": "communications",
    "28": "healthcare",
    "29": "energy",
    "30": "materials",
    "31": "materials",
    "32": "materials",
    "33": "materials",
    "34": "industrials",
    "35": "industrials",
    "36": "technology",
    "37": "industrials",
    "38": "technology",
    "39": "industrials",
    "40": "industrials",
    "41": "industrials",
    "42": "industrials",
    "44": "industrials",
    "45": "industrials",
    "47": "industrials",
    "48": "communications",
    "49": "utilities",
    "50": "industrials",
    "51": "industrials",
    "52": "consumer",
    "53": "consumer",
    "54": "consumer",
    "55": "consumer",
    "56": "consumer",
    "57": "consumer",
    "58": "consumer",
    "59": "consumer",
    "60": "financials",
    "61": "financials",
    "62": "financials",
    "63": "financials",
    "64": "financials",
    "65": "real_estate",
    "67": "financials",
    "70": "consumer",
    "72": "consumer",
    "73": "technology",
    "75": "consumer",
    "78": "communications",
    "79": "consumer",
    "80": "healthcare",
}
EXACT = {"2844": "consumer", "2899": "materials"}


def sector_for(sic: str) -> str | None:
    return EXACT.get(sic) or DIVISIONS.get(sic[:2])


def fetch(start: str, end: str) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "q": '"current report"',
            "forms": "8-K",
            "dateRange": "custom",
            "startdt": start,
            "enddt": end,
        }
    )
    url = f"https://efts.sec.gov/LATEST/search-index?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())["hits"]["hits"]


def company(source: dict) -> str:
    raw = (source.get("display_names") or [""])[0]
    return raw.split("  (")[0].strip()


def build() -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for start, end in MONTHS:
        kept = 0
        for hit in fetch(start, end):
            source = hit["_source"]
            sic = (source.get("sics") or [""])[0]
            sector = sector_for(sic)
            cik = (source.get("ciks") or [""])[0]
            name = company(source)
            if sector is None or not name or cik in seen:
                continue
            seen.add(cik)
            rows.append(
                {
                    "id": len(rows) + 1,
                    "subject": f"{name.lower()} files form 8-k with the sec",
                    "sector": sector,
                    "verdict": None,
                    "reason": f"EDGAR SIC {sic} (division {sic[:2]}) is {sector}",
                    "provenance": (
                        f"SEC EDGAR full-text search, form 8-K, filed "
                        f"{source['file_date']}, accession {source['adsh']}"
                    ),
                    "published_at": source["file_date"],
                }
            )
            kept += 1
            if kept >= PER_MONTH:
                break
    return rows


def write() -> int:
    rows = build()
    payload = "\n".join(json.dumps(row, ensure_ascii=True) for row in rows) + "\n"
    OUT.write_text(payload, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    MANIFEST.write_text(
        json.dumps(
            {
                "label": "public sample, not production",
                "source": "SEC EDGAR full-text search API",
                "source_urls": [
                    "https://efts.sec.gov/LATEST/search-index?q=%22current+report%22"
                    f"&forms=8-K&dateRange=custom&startdt={start}&enddt={end}"
                    for start, end in MONTHS
                ],
                "licence": "US government work, public domain; SEC fair-access policy",
                "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "rows": len(rows),
                "sha256": digest,
                "label_rule": "SIC division table in scripts/gold_public_sample.py",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{OUT.relative_to(ROOT)}: {len(rows)} rows, sha256 {digest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="fetch and freeze the sample"
    )
    args = parser.parse_args(argv)
    if not args.write:
        parser.error("--write is the only mode")
    return write()


if __name__ == "__main__":
    raise SystemExit(main())
