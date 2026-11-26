"""Daily data-quality report: `python -m worker.quality [--days N]`.

Covers the event columns the desk filters and ranks on — sector, tickers, signal score
and confidence — plus duplicate stories (the same article URL attached to more than one
event) in the window.

Report-only on purpose. A missing sector or ticker can be legitimate: some stories are
macro or unlisted and nothing is lost by leaving them empty, so the rate is a trend to
watch, not a failure. Out-of-range confidence (outside 0..1) and a story URL shared by
several events are defects — the model wrote an impossible probability, or ingest
double-counted one article — so a report with any of those exits non-zero while never
rewriting rows. The scheduled job only logs.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from server import db
from server.settings import get_settings

log = logging.getLogger("worldfin.worker.quality")

EVENTS_SQL = """
SELECT count(*) AS events,
       count(*) FILTER (WHERE btrim(sector_impact) = '') AS missing_sector,
       count(*) FILTER (WHERE jsonb_array_length(tickers) = 0) AS missing_tickers,
       count(*) FILTER (WHERE signal_score = 0) AS no_score,
       count(*) FILTER (WHERE confidence < 0 OR confidence > 1) AS out_of_range
FROM events
WHERE timestamp >= now() - ($1 || ' days')::interval
"""

DUPLICATES_SQL = """
WITH story AS (
    SELECT e.id, u.url
    FROM events e
    CROSS JOIN LATERAL jsonb_array_elements_text(e.articles) AS u(url)
    WHERE e.timestamp >= now() - ($1 || ' days')::interval
)
SELECT count(*) AS urls, coalesce(sum(n - 1), 0) AS extra
FROM (
    SELECT url, count(DISTINCT id) AS n
    FROM story
    GROUP BY url
    HAVING count(DISTINCT id) > 1
) d
"""


@dataclass(frozen=True)
class QualityReport:
    days: int
    events: int
    missing_sector: int
    missing_tickers: int
    no_score: int
    out_of_range: int
    duplicate_urls: int
    duplicate_extra: int

    def rate(self, n: int) -> float:
        """Share of events, 0.0 on an empty window instead of dividing by zero."""
        return n / self.events if self.events else 0.0

    @property
    def defects(self) -> int:
        """Only true defects: impossible confidence and duplicated stories."""
        return self.out_of_range + self.duplicate_extra

    def summary(self) -> str:
        return (
            f"quality {self.days}d: {self.events} events; "
            f"sector missing {self.missing_sector} ({self.rate(self.missing_sector):.1%}), "
            f"tickers missing {self.missing_tickers} ({self.rate(self.missing_tickers):.1%}), "
            f"score 0 on {self.no_score} ({self.rate(self.no_score):.1%}), "
            f"confidence out of range {self.out_of_range}, "
            f"duplicate stories {self.duplicate_urls} URLs / "
            f"{self.duplicate_extra} extra rows"
        )


def _int(value: Any) -> int:
    return int(value or 0)


async def collect(pool: Any, days: int = 1) -> QualityReport:
    """Two read-only counts over the window; missing values map to 0."""
    totals = await pool.fetchrow(EVENTS_SQL, str(days))
    dupes = await pool.fetchrow(DUPLICATES_SQL, str(days))
    return QualityReport(
        days=days,
        events=_int(totals["events"]),
        missing_sector=_int(totals["missing_sector"]),
        missing_tickers=_int(totals["missing_tickers"]),
        no_score=_int(totals["no_score"]),
        out_of_range=_int(totals["out_of_range"]),
        duplicate_urls=_int(dupes["urls"]),
        duplicate_extra=_int(dupes["extra"]),
    )


async def run(pool: Any, days: int = 1) -> QualityReport:
    """Collect and log; a defect report is a warning, never an exception."""
    report = await collect(pool, days)
    if report.defects:
        log.warning(report.summary())
    else:
        log.info(report.summary())
    return report


async def _report(days: int) -> int:
    """Read-only: connect, count, disconnect. No migrations on a report job."""
    pool = await db.connect(get_settings().database_url, min_size=1, max_size=2)
    try:
        report = await collect(pool, days)
    finally:
        await db.disconnect()
    print(report.summary())
    for label, n in (
        ("sector missing", report.missing_sector),
        ("tickers missing", report.missing_tickers),
        ("score 0", report.no_score),
        ("confidence out of range", report.out_of_range),
        ("duplicate URLs", report.duplicate_urls),
        ("duplicate extra rows", report.duplicate_extra),
    ):
        print(f"  {label}: {n} ({report.rate(n):.1%})")
    return 1 if report.defects else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="daily data-quality report")
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args(argv)
    return asyncio.run(_report(args.days))


if __name__ == "__main__":
    raise SystemExit(main())
