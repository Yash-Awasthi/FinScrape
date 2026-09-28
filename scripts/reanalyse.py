"""Re-run LLM analysis on events stored with the heuristic fallback, in place.

When the LLM is down the worker stores heuristic verdicts (key_metrics.prompt_variant
= "heuristic") so ingestion never stalls. Once an LLM is back, this upgrades those
rows from their headline; rows it judges off-topic are tagged "rejected", which the
feed and scenarios skip. Rows the LLM fails on stay heuristic for the next run.

    python scripts/reanalyse.py [--days 14] [--limit 1000] [--workers 4] [--dry-run]

Reads WORLDFIN_DATABASE_URL and the usual LLM env (OPENAI_BASE_URL, OPENAI_API_KEY,
FINSCRAPE_MODEL, FINSCRAPE_WIRE_API).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finscrape.models import ScrapedArticle  # noqa: E402
from finscrape.pipeline import FinScrapePipeline  # noqa: E402
from server import db  # noqa: E402
from server.settings import get_settings  # noqa: E402

_SET = """
UPDATE events SET event_type = $2, impact_direction = $3, signal_score = $4,
    confidence = $5, verdict = $6, heuristic_impact = $7, divergence_flag = $8,
    reasoning = $9, magnitude = $10, novelty = $11, actionability = $12,
    sector_impact = $13, tickers = $14, affected_entities = $15,
    second_order_effects = $16, key_metrics = $17
WHERE id = $1
"""


# The LLM judged it off-topic; the row stays for the record but leaves feed and scenarios.
_REJECT = """
UPDATE events SET key_metrics = key_metrics || '{"prompt_variant": "rejected"}'::jsonb
WHERE id = $1
"""


class _NoDedup:
    """Each row is re-judged on its own; it must not merge into its neighbours."""

    events: list[dict] = []

    def add_event(self, event: dict) -> int:
        return 0

    def update_event(self, event_id: int, **kwargs: Any) -> None:
        pass


def analyse(pipeline: FinScrapePipeline, row: dict) -> tuple[int, Any, bool]:
    sources = row["sources"] or ["unknown"]
    article = ScrapedArticle(
        url=(row["articles"] or [f"event://{row['id']}"])[0],
        title=row["subject"],
        text=row["subject"],
        source=sources[0],
    )
    event = pipeline._analyze_article(sources[0], article)
    return row["id"], event, pipeline.ai_failed()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pool = await db.connect(get_settings().database_url, min_size=1, max_size=4)
    rows = [
        dict(r)
        for r in await pool.fetch(
            """
        SELECT id, subject, sources, articles FROM events
        WHERE key_metrics->>'prompt_variant' = 'heuristic'
          AND timestamp > now() - make_interval(days => $1)
        ORDER BY timestamp DESC LIMIT $2
        """,
            args.days,
            args.limit,
        )
    ]
    print(f"{len(rows)} heuristic events in the last {args.days} days", flush=True)

    pipeline = FinScrapePipeline(_NoDedup())
    updated = kept = rejected = 0
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(args.workers) as ex:
        futures = [loop.run_in_executor(ex, analyse, pipeline, r) for r in rows]
        for i, fut in enumerate(asyncio.as_completed(futures), 1):
            event_id, ev, failed = await fut
            if ev is None and failed:
                kept += 1  # LLM error: stays heuristic so a later run retries it
            elif ev is None:
                rejected += 1
                if not args.dry_run:
                    await pool.execute(_REJECT, event_id)
            elif not args.dry_run:
                e = ev.to_dict()
                await pool.execute(
                    _SET,
                    event_id,
                    e["event_type"],
                    e["impact_direction"],
                    int(e["signal_score"]),
                    float(e["confidence"]),
                    e["verdict"],
                    float(e["heuristic_impact"]),
                    bool(e["divergence_flag"]),
                    e["reasoning"],
                    e["magnitude"],
                    e["novelty"],
                    e["actionability"],
                    e["sector_impact"],
                    e["tickers"],
                    e["affected_entities"],
                    e["second_order_effects"],
                    e["key_metrics"],
                )
                updated += 1
            if i % 50 == 0:
                print(
                    f"  {i}/{len(rows)}: {updated} updated, {rejected} rejected, "
                    f"{kept} failed",
                    flush=True,
                )
    print(f"done: {updated} updated, {rejected} rejected, {kept} failed", flush=True)
    await db.disconnect()


if __name__ == "__main__":
    os.environ.setdefault("FINSCRAPE_LAYA", "0")
    asyncio.run(main())
