"""Weekly backfill append (docs/BACKFILL.md): `python -m scripts.backfill.weekly`.

Run on Saturdays by the Windows task `WorldFin backfill weekly`. Refreshes prices,
rebuilds the event files of the months the last week touched (a rebuild is idempotent
where an append is not), then recomputes `outcomes.parquet`. The universe stays as built.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from scripts.backfill import gdelt_month, outcomes
from scripts.backfill.universe import OUT, check, fetch_prices

WEEK = 8  # days: a Saturday run reaches back past last Friday's after-close news


def months(today: date) -> list[str]:
    return sorted({d.strftime("%Y-%m") for d in (today - timedelta(days=WEEK), today)})


def main() -> int:
    uni = pd.read_parquet(OUT / "universe.parquet")
    prices = fetch_prices(uni["ticker"].tolist() + ["SPY"])
    old = pd.read_parquet(OUT / "prices.parquet")
    # A Yahoo outage returns a short frame; overwriting with it would drop history.
    if prices["date"].max() < old["date"].max() or len(prices) < 0.95 * len(old):
        print(f"prices refresh looks short ({len(prices):,} rows, had {len(old):,})")
        return 1
    prices.to_parquet(OUT / "prices.parquet", index=False)
    if check(uni, prices):
        print("prices check failed; events and outcomes not rebuilt")
        return 1
    for m in months(datetime.now(UTC).date()):
        print(f"== events {m}")
        if gdelt_month.main(m):
            return 1
    print("== outcomes")
    return outcomes.main()


if __name__ == "__main__":
    sys.exit(main())
