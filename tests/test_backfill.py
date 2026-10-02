"""Backfill universe build (scripts/backfill); no network."""

from __future__ import annotations

import pandas as pd

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
