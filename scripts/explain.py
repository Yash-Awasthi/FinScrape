"""EXPLAIN the read queries the API actually issues, and publish the plans (plan M3.2).

A query plan is evidence, not a guess: the file this writes names the index each hot
read uses (or the sequential scan it cannot avoid), against a table with enough rows for
the planner to care. Run against a dedicated database — `--seed` inserts synthetic rows.

    python -m scripts.explain --dsn "$WORLDFIN_TEST_DATABASE_URL" --seed 20000 --write
    python -m scripts.explain --dsn ... --check     # fails if a filtered read seq-scans

`--check` is deliberately narrow: only the reads that *filter* events must be
index-backed. The dashboard totals (`count(*)`, `max(created_at)`) are full-table
aggregates and a sequential scan is the correct plan for them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

DEFAULT_DSN = "postgresql://postgres@127.0.0.1:5439/worldfin_test"
DOC = "docs/QUERIES.md"


@dataclass(frozen=True)
class Query:
    key: str
    label: str
    sql: str
    args: tuple = ()
    filtered: bool = False  # a filter + ORDER BY read: must not seq-scan events


QUERIES: tuple[Query, ...] = (
    Query(
        "events_verdict",
        "Feed, one verdict (the common filtered read)",
        "SELECT * FROM events WHERE verdict = $1 AND timestamp >= $2 "
        "ORDER BY id DESC LIMIT 50 OFFSET 0",
        ("INVEST", datetime(2020, 1, 1, tzinfo=UTC)),
        filtered=True,
    ),
    Query(
        "events_ticker",
        "Feed, one ticker (jsonb membership)",
        "SELECT * FROM events WHERE tickers ? $1 ORDER BY id DESC LIMIT 50",
        ("XOM",),
        filtered=True,
    ),
    Query(
        "events_date",
        "Feed, one day",
        "SELECT * FROM events WHERE timestamp >= $1 AND timestamp < $2 "
        "ORDER BY id DESC LIMIT 50",
        (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)),
        filtered=True,
    ),
    Query(
        "stats",
        "Dashboard totals",
        "SELECT count(*) AS total, max(created_at) AS last FROM events",
    ),
    Query(
        "accuracy",
        "Track record join",
        "SELECT e.verdict, count(*) AS n, "
        "avg(CASE WHEN o.correct THEN 1.0 ELSE 0.0 END) AS hit "
        "FROM accuracy_outcomes o JOIN events e ON e.id = o.event_id GROUP BY e.verdict",
    ),
    Query(
        "correlations",
        "Recent correlation signals",
        "SELECT * FROM correlations ORDER BY detected_at DESC LIMIT 20",
    ),
    Query(
        "storylines_head",
        "Storylines cache key (newest 200)",
        "SELECT max(id) AS newest, count(*) AS considered FROM "
        "(SELECT id FROM events ORDER BY id DESC LIMIT 200) w",
    ),
)


async def seed(conn: asyncpg.Connection, rows: int) -> None:
    await conn.execute(
        """
        INSERT INTO events (content_hash, subject, event_type, verdict, timestamp,
                            signal_score, reasoning, tickers, sources, sector_impact)
        SELECT 'explain-' || g,
               'Synthetic story ' || g,
               (ARRAY['earnings','macro','energy'])[1 + g % 3],
               (ARRAY['INVEST','OBSERVE','PULL_OUT','CAUTIOUS'])[1 + g % 4],
               now() - (g || ' minutes')::interval,
               (g % 11) - 5,
               'seed row for query plans',
               jsonb_build_array((ARRAY['XOM','CVX','JPM','AAPL'])[1 + g % 4]),
               jsonb_build_array('world/reuters'),
               (ARRAY['Energy','Financials','Technology'])[1 + g % 3]
        FROM generate_series(1, $1) AS g
        ON CONFLICT (content_hash) DO NOTHING
        """,
        rows,
    )
    await conn.execute("ANALYZE events")
    await conn.execute("ANALYZE accuracy_outcomes")
    await conn.execute("ANALYZE correlations")


def _plan_rows(payload: list[dict]) -> list[dict]:
    root = payload[0]["Plan"]
    out: list[dict] = []

    def walk(node: dict, depth: int) -> None:
        out.append(
            {
                "depth": depth,
                "node": node.get("Node Type", "?"),
                "relation": node.get("Relation Name", ""),
                "index": node.get("Index Name", ""),
                "rows": node.get("Actual Rows"),
                "time_ms": round(node.get("Actual Total Time", 0.0), 3),
                "filter": node.get("Filter", ""),
            }
        )
        for child in node.get("Plans", []):
            walk(child, depth + 1)

    walk(root, 0)
    return out


def seq_scans_events(plan: list[dict]) -> bool:
    return any(
        row["node"] == "Seq Scan" and row["relation"] == "events" for row in plan
    )


def used_indexes(plan: list[dict]) -> list[str]:
    seen: list[str] = []
    for row in plan:
        name = row["index"]
        if name and name not in seen:
            seen.append(name)
    return seen


async def explain_all(dsn: str, seed_rows: int) -> dict[str, dict]:
    conn = await asyncpg.connect(dsn)
    try:
        if seed_rows:
            await seed(conn, seed_rows)
        results: dict[str, dict] = {}
        for query in QUERIES:
            payload = await conn.fetchval(
                f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query.sql}", *query.args
            )
            # asyncpg returns json as text for a json column; EXPLAIN returns jsonb text.
            data = json.loads(payload) if isinstance(payload, str) else payload
            plan = _plan_rows(data)
            results[query.key] = {
                "label": query.label,
                "filtered": query.filtered,
                "plan": plan,
                "indexes": used_indexes(plan),
                "seq_scan_events": seq_scans_events(plan),
            }
        return results
    finally:
        await conn.close()


def render(results: dict[str, dict], dsn: str, seeded: int) -> str:
    database = re.sub(r"://[^@]*@", "://***@", dsn)
    lines = [
        "# Hot query plans",
        "",
        "Generated by `python -m scripts.explain --write` against",
        f"`{database}` with **{seeded}** synthetic events. Do not hand-edit: the point of",
        "this file is that the plans are reproduced, not asserted. `make explain-check`",
        "fails when a filtered feed read no longer uses an index.",
        "",
        "The plan's schema mapping: the plan names `published_at`/`topic`/`ticker`; the",
        "table stores `timestamp`, `event_type`/`sector_impact` and `tickers` (jsonb, GIN).",
        "",
        "| Read | Index used | Plan (top node → leaf) | Time (ms) |",
        "|---|---|---|---|",
    ]
    for key, result in results.items():
        chain = " → ".join(
            f"{row['node']}"
            + (f"({row['relation']})" if row["relation"] else "")
            + (f"[{row['index']}]" if row["index"] else "")
            for row in result["plan"]
        )
        indexes = ", ".join(f"`{i}`" for i in result["indexes"]) or "**sequential**"
        total = sum(row["time_ms"] for row in result["plan"] if row["depth"] == 0)
        lines.append(
            f"| {result['label']} (`{key}`) | {indexes} | {chain} | {total:.3f} |"
        )
    lines += [
        "",
        "## What `--check` enforces",
        "",
        "Only the filtered reads (feed by verdict, ticker, day) must avoid a sequential",
        "scan of `events`. Aggregates (`count(*)`, `max(created_at)`) and the small",
        "`correlations`/`accuracy_outcomes` joins are allowed to scan: a seq scan is the",
        "correct plan when the read covers the whole table.",
        "",
    ]
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn", default=os.environ.get("WORLDFIN_EXPLAIN_DSN", DEFAULT_DSN)
    )
    parser.add_argument("--seed", type=int, default=20000)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    results = await explain_all(args.dsn, args.seed)
    if args.write:
        # A one-shot CLI: the write is the last thing before exit, so the blocking open
        # costs nothing an event loop could use.
        with open(DOC, "w", encoding="utf-8") as handle:  # noqa: ASYNC230
            handle.write(render(results, args.dsn, args.seed))
        print(f"explain: wrote {DOC} ({len(results)} reads)")
    for key, result in results.items():
        if result["filtered"]:
            verdict = "SEQ SCAN" if result["seq_scan_events"] else "index"
            print(f"  {key:<16} {verdict:<9} {', '.join(result['indexes']) or '-'}")
    if args.check:
        bad = [
            key
            for key, result in results.items()
            if result["filtered"] and result["seq_scan_events"]
        ]
        if bad:
            print(f"explain: filtered reads are not index-backed: {', '.join(bad)}")
            return 1
        print("explain: every filtered feed read is index-backed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
