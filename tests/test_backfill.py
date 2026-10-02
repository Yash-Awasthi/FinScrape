"""Backfill universe build (scripts/backfill); no network."""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from scripts.backfill.gdelt_month import COLUMNS, build, matcher, parse_export
from scripts.backfill.outcomes import outcomes
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


def test_outcomes_use_the_last_close_before_the_news():
    days = pd.bdate_range("2026-09-07", "2026-09-18")  # Mon 7th to Fri 18th
    prices = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": days,
                    "ticker": "XOM",
                    "close": [100.0 + i for i in range(len(days))],
                }
            ),
            pd.DataFrame({"date": days, "ticker": "SPY", "close": 100.0}),
        ]
    )
    utc = lambda s: pd.Timestamp(s, tz="America/New_York").tz_convert("UTC")
    events = pd.DataFrame(
        {
            "event_id": [1, 2, 3, 4],
            "added_utc": [
                utc("2026-09-09 10:00"),  # Wed before the close: Tue's close
                utc("2026-09-09 16:30"),  # Wed after the close: Wed's close
                utc("2026-09-12 11:00"),  # Saturday: Fri's close
                utc("2026-09-16 17:00"),  # Wed after close, +4 days runs past the data
            ],
            "tickers": [["XOM"]] * 4,
        }
    )
    out = outcomes(events, prices).set_index("event_id")
    assert str(out.loc[1, "base_date"].date()) == "2026-09-08"
    assert str(out.loc[2, "base_date"].date()) == "2026-09-09"
    assert str(out.loc[3, "base_date"].date()) == "2026-09-11"
    assert out.loc[1, "ret2"] == pytest.approx(103 / 101 - 1)
    assert out.loc[1, "spy4"] == 0 and out.loc[1, "ex4"] == pytest.approx(105 / 101 - 1)
    assert pd.notna(out.loc[4, "ret2"]) and pd.isna(out.loc[4, "ret4"])


def test_outcomes_drop_windows_across_an_unadjusted_spin_off(monkeypatch):
    import scripts.backfill.outcomes as mod

    days = pd.bdate_range("2026-09-07", "2026-09-11")
    prices = pd.concat(
        [
            pd.DataFrame(
                {"date": days, "ticker": "CTVA", "close": [80.0, 80, 80, 13, 13]}
            ),
            pd.DataFrame({"date": days, "ticker": "SPY", "close": 100.0}),
        ]
    )
    monkeypatch.setattr(mod, "UNADJUSTED", {"CTVA": "2026-09-10"})
    events = pd.DataFrame(
        {
            "event_id": [1, 2],
            "added_utc": pd.to_datetime(
                ["2026-09-07 21:00", "2026-09-09 21:00"], utc=True
            ),
            "tickers": [["CTVA"], ["CTVA"]],
        }
    )
    out = outcomes(events, prices).set_index("event_id")
    assert pd.isna(out.loc[1, "ex4"]) and pd.isna(out.loc[2, "ex2"])


def test_contest_report_applies_keep_rule():
    from scripts.backfill.sector_contest import by_familiarity, report

    truth = ["energy"] * 6 + ["technology"] * 4
    frame = pd.DataFrame(
        {
            "split": ["test"] * 10 + ["none"] * 2,
            "truth": truth + ["", ""],
            "base": ["energy"] * 5 + ["other"] * 5 + ["other", "other"],
            "model": truth[:9] + ["energy"] + ["energy", "other"],
            "model alone": truth + ["energy", "energy"],
        }
    )
    text = report(frame, ["base", "model", "model alone"], min_n=10)
    assert "| base | 50.0% | 100.0% | 0.0% |" in text
    assert "| model | 90.0% | 50.0% | 50.0% |" in text
    assert "| energy | 6 | 83.3 | 100.0 | 100.0 |" in text
    assert "`model` leads `base` by +40.0 points; kept" in text
    assert "not kept" in report(frame, ["base", "model"], min_n=11)

    frame["ticker"] = ["XOM"] * 6 + ["NEW"] * 4 + ["", ""]
    table = by_familiarity(frame, pd.Series({"XOM": 120}), ["model"])
    assert "| never | 4 | 75.0 |" in table
    assert "| 100+ | 6 | 100.0 |" in table
