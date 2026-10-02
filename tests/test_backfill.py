"""Backfill universe build (scripts/backfill); no network."""

from __future__ import annotations

import io
import zipfile

import pandas as pd

from scripts.backfill.gdelt_month import COLUMNS, build, matcher, parse_export
from scripts.backfill.universe import build_universe, short_name


def test_short_name_strips_suffixes_and_share_class():
    assert short_name("Alphabet Inc. (Class A)") == "alphabet"
    assert short_name("Home Depot (The)") == "home depot"
    assert short_name("Brown–Forman") == "brown forman"
    assert short_name("Estée Lauder Companies (The)") == "estee lauder companies"


def test_universe_maps_sectors_and_keeps_one_name_per_company(tmp_path):
    table = pd.DataFrame(
        {
            "Symbol": ["GOOGL", "GOOG", "BRK.B", "TGT", "NWSA"],
            "Security": [
                "Alphabet Inc. (Class A)",
                "Alphabet Inc. (Class C)",
                "Berkshire Hathaway",
                "Target Corporation",
                "News Corp (Class A)",
            ],
            "GICS Sector": [
                "Communication Services",
                "Communication Services",
                "Financials",
                "Consumer Staples",
                "Communication Services",
            ],
        }
    )
    uni = build_universe(table)
    uni.to_parquet(tmp_path / "u.parquet", index=False)
    back = pd.read_parquet(tmp_path / "u.parquet").set_index("ticker")
    assert list(back.columns) == ["name", "gics_sector", "sector", "aliases"]
    assert back.loc["GOOGL", "sector"] == "communications"
    assert "alphabet" in back.loc["GOOGL", "aliases"]
    assert len(back.loc["GOOG", "aliases"]) == 0
    assert back.loc["BRK-B", "sector"] == "financials"
    assert "target" not in back.loc["TGT", "aliases"]
    assert list(back.loc["NWSA", "aliases"]) == ["news corp"]


def _export(rows: list[list[str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.export.CSV", "\n".join("\t".join(r) for r in rows))
    return buf.getvalue()


def _row(eid: str, url: str, mentions: str) -> list[str]:
    r = [""] * 61
    r[0], r[26], r[29], r[30], r[31], r[34] = eid, "190", "4", "-10", mentions, "-3.5"
    r[53], r[56], r[57], r[59], r[60] = "US", "38.9", "-77.0", "20260915120000", url
    return r


def test_month_rows_dedupe_by_url_and_tag_single_companies(tmp_path):
    universe = pd.DataFrame(
        {
            "ticker": ["XOM", "CVX", "TGT"],
            "aliases": [["exxon mobil", "exxon"], ["chevron"], ["target corp"]],
        }
    )
    a = "https://www.example.com/news/exxon-mobil-cuts-output-after-storm"
    b = "https://example.com/news/exxon-and-chevron-raise-output-in-texas"
    c = "https://example.com/news/target-practice-at-the-range-today"
    data = _export(
        [_row("1", a, "2"), _row("2", a, "9"), _row("3", b, "1"), _row("4", c, "1")]
    )
    df = build(parse_export(data), matcher(universe))
    df.to_parquet(tmp_path / "m.parquet", index=False)
    back = pd.read_parquet(tmp_path / "m.parquet").set_index("event_id")
    assert list(back.reset_index().columns) == COLUMNS
    assert len(back) == 3 and back.loc[2, "mentions"] == 9
    assert (
        list(back.loc[2, "tickers"]) == ["XOM"]
        and back.loc[2, "domain"] == "example.com"
    )
    assert (
        list(back.loc[3, "tickers"]) == ["CVX", "XOM"]
        and back.loc[3, "n_companies"] == 2
    )
    assert back.loc[4, "n_companies"] == 0
    assert str(back.loc[2, "added_utc"]) == "2026-09-15 12:00:00+00:00"
