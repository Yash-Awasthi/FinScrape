"""Entity index over 100 real headlines (plan M5.1: ticker coverage).

The 25-symbol overlap in `server.correlate._topics_by_ticker()` is what the market
bridge prices. This measures what the merged entity index can *name* across ids 1..100
of the frozen gold set, and pins the measured floor so a data edit that loses coverage
fails instead of drifting silently.
"""

import json
import warnings
from pathlib import Path

from finscrape.extract import entity_map
from finscrape.extract.entity_index import (
    PRODUCT_KEYS,
    SOURCES,
    resolve,
    resolve_detailed,
)

GOLD = Path(__file__).with_name("gold") / "sector_set.jsonl"
ROWS = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines()]
ROWS = [row for row in ROWS if 1 <= row["id"] <= 100]

# Measured 2026-11-26 over ids 1..100: 51 headlines resolve to >= 1 symbol, 50 distinct
# symbols. The product entries added with this test do not appear in these macro and
# geopolitics headlines, so they move the symbol vocabulary, not this coverage number.
MEASURED_COVERAGE = 51


def test_audit_every_resolution_names_its_source():
    pairs = [
        (row["id"], row["subject"], symbol, source)
        for row in ROWS
        for symbol, source in resolve_detailed(row["subject"])
    ]
    assert pairs, "the index resolved nothing on the gold set"
    assert {source for *_, source in pairs} <= SOURCES
    for headline_id, subject, symbol, source in pairs:
        print(f"{headline_id:3d} | {symbol:5s} | {source:13s} | {subject}")


def test_coverage_over_100_gold_headlines():
    assert len(ROWS) == 100, f"expected ids 1..100, loaded {len(ROWS)}"
    per_row = [resolve(row["subject"]) for row in ROWS]
    covered = sum(1 for symbols in per_row if symbols)
    symbols = sorted({symbol for row in per_row for symbol in row})
    summary = (
        f"entity index coverage {covered}/100 headlines ({covered} percent), "
        f"{len(symbols)} distinct symbols, floor {MEASURED_COVERAGE}/100; "
        f"symbols: {' '.join(symbols)}"
    )
    print(summary)
    warnings.warn(summary, stacklevel=1)
    assert covered >= MEASURED_COVERAGE, summary


def test_negative_set_mints_no_company_product_or_legal_ticker():
    for text in (
        "analyst raised price target on the stock",
        "arm wrestlers compete",
        "the company reported earnings",
    ):
        assert resolve(text) == [], text
    # "pharma" and "pipeline" are sector keywords, so that layer legitimately returns
    # liquid proxies; what must not fire is a company/product/legal false hit such as
    # TGT (target corp) or ARM (arm holdings).
    detailed = resolve_detailed("pharma pipeline update")
    assert detailed, "the sector layer should still resolve pharma/pipeline"
    assert {source for _, source in detailed} == {"keyword"}
    assert "TGT" not in resolve("pharma pipeline update")
    assert "ARM" not in resolve("pharma pipeline update")


def test_obvious_symbols():
    assert "NVDA" in resolve("nvidia unveils new chip")
    assert resolve("apple iphone sales fall") == ["AAPL"]


def test_product_entries_are_loaded_and_resolve():
    forward = entity_map._forward()
    missing = PRODUCT_KEYS - set(forward)
    assert not missing, f"product keys not loaded from entity_index.json: {sorted(missing)}"
    assert resolve("azure growth slows") == ["MSFT"]
    assert resolve("the h100 ships this quarter") == ["NVDA"]
