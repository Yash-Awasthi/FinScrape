"""Excess returns after each tagged event: `python -m scripts.backfill.outcomes`.

Writes data/backfill/outcomes.parquet, one row per (event, named ticker). The base is the
last close before the news: news after 16:00 ET, or on a closed day, uses that day's last
close. Returns run from the base close to +2 and +4 trading days, against SPY's.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("data/backfill")
HORIZONS = (2, 4)
# ponytail: spin-offs Yahoo had not yet back-adjusted when prices were pulled; windows
# crossing the date are dropped. Check new big one-day drops by hand on each refresh.
UNADJUSTED = {"CTVA": "2026-10-01"}


def outcomes(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    close = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    days = close.index.values
    et = pd.to_datetime(events["added_utc"], utc=True).dt.tz_convert("America/New_York")
    # ponytail: half-day 13:00 closes are treated as 16:00; a handful of events a year.
    cutoff = et.dt.tz_localize(None).dt.normalize() - pd.to_timedelta(
        np.where(et.dt.hour < 16, 1, 0), unit="D"
    )
    base_idx = np.searchsorted(days, cutoff.values, side="right") - 1

    ev = events.assign(base_idx=base_idx)[["event_id", "tickers", "base_idx"]]
    ev = (
        ev.explode("tickers")
        .rename(columns={"tickers": "ticker"})
        .dropna(subset=["ticker"])
    )
    ev = ev[(ev["base_idx"] >= 0) & ev["ticker"].isin(close.columns)]
    i = ev["base_idx"].to_numpy()
    out = ev[["event_id", "ticker"]].assign(base_date=days[i])

    matrix = close.to_numpy()
    col = close.columns.get_indexer(ev["ticker"])
    spy = close.columns.get_loc("SPY")
    for h in HORIZONS:
        j = i + h
        ok = j < len(days)
        jj = np.where(ok, j, 0)
        out[f"ret{h}"] = np.where(ok, matrix[jj, col] / matrix[i, col] - 1, np.nan)
        out[f"spy{h}"] = np.where(ok, matrix[jj, spy] / matrix[i, spy] - 1, np.nan)
        for ticker, day in UNADJUSTED.items():
            crosses = (
                (out["ticker"] == ticker)
                & (out["base_date"] < day)
                & (days[jj] >= np.datetime64(day))
            )
            out.loc[crosses & ok, f"ret{h}"] = np.nan
        out[f"ex{h}"] = out[f"ret{h}"] - out[f"spy{h}"]
    return out.reset_index(drop=True)


def main() -> int:
    prices = pd.read_parquet(OUT / "prices.parquet")
    files = sorted((OUT / "events").glob("*.parquet"))
    want = pd.period_range("2023-10", pd.Timestamp.now(), freq="M").astype(str)
    if missing := sorted(set(want) - {f.stem for f in files if f.stat().st_size}):
        print(f"missing months: {missing}")
        return 1
    cols = ["event_id", "added_utc", "url", "tickers", "n_companies"]
    # Same URL gives the same slug and tags, so only tagged rows need cross-month dedup.
    tagged = [("n_companies", ">", 0)]
    events = pd.concat(pd.read_parquet(f, columns=cols, filters=tagged) for f in files)
    total = len(events)
    # Months are deduplicated alone; a story re-coded next month keeps its first sighting.
    events = events.sort_values("added_utc").drop_duplicates("url")
    repeated = total - len(events)
    out = outcomes(events, prices)
    out.to_parquet(OUT / "outcomes.parquet", index=False)

    single = events[events["n_companies"] == 1]
    month = single["added_utc"].dt.strftime("%Y-%m")
    scored = single["event_id"].isin(out.dropna(subset=["ex4"])["event_id"])
    last_base = sorted(prices["date"].unique())[-max(HORIZONS) - 1]
    base = out.drop_duplicates("event_id").set_index("event_id")["base_date"]
    is_open = single["event_id"].map(base) > last_base
    print(f"months {len(files)}: {files[0].stem} to {files[-1].stem}")
    print(f"tagged events {total:,}, repeated URLs across months dropped {repeated:,}")
    print(
        f"tagged {len(events):,}, outcome rows {len(out):,}, single-company {len(single):,}"
    )
    print(
        f"single-company with ex4 {scored.sum():,} ({scored.mean():.1%}); "
        f"+4 window still open {is_open.sum():,}; no price {(~scored & ~is_open).sum():,}"
    )
    print(scored.groupby(month).agg(["size", "mean"]).round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
