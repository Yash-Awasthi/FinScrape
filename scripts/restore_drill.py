"""Prove a backup can be restored, and time it (plan M2.5).

    python -m scripts.restore_drill                        # dump the test DB, restore it
    python -m scripts.restore_drill --dump backups/worldfin.dump.enc --record

What it does, and why each step exists:

1. **Get a dump.** Either `pg_dump -Fc` the source, or decrypt an existing `.enc` backup with
   `BACKUP_KEY` — the encrypted file is what actually exists after an incident, so the drill
   has to be able to start from it.
2. **Verify the dump before trusting it.** `pg_restore --list` on a truncated or empty file
   fails here, which is the difference between "we have a backup" and "we have a file".
3. **Restore into a scratch database** (`<source>_drill`), created and dropped around the
   run so the drill never touches the source.
4. **Compare row counts** table by table against the source, and fail on a mismatch: a
   restore that silently loses the events table is worse than no restore.
5. **Check the app can serve it** — the same `/api/stats` aggregate the dashboard uses.
6. **Record the time** in `docs/RUNBOOK.md` with `--record`, because a restore nobody timed
   is a restore nobody knows the cost of.

Needs `pg_dump`/`pg_restore` (PATH, `PG_BIN`, or the default Windows install) and a
`*_test` source database by default, so a drill cannot be pointed at production by accident.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from scripts.pg import tool, verify_dump

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"
DRILL_SUFFIX = "_drill"
# The tables whose loss would make the dashboard lie about itself.
CRITICAL_TABLES = ("events", "accuracy_outcomes", "correlations", "source_health")


def _source_dsn() -> str:
    dsn = os.getenv("WORLDFIN_TEST_DATABASE_URL") or os.getenv("WORLDFIN_DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "set WORLDFIN_TEST_DATABASE_URL (a *_test database) to drill against"
        )
    return dsn


def _with_database(dsn: str, database: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path=f"/{database}"))


def _database(dsn: str) -> str:
    return urlparse(dsn).path.lstrip("/")


def decrypt(source: Path, key: str, target: Path) -> Path:
    """`openssl enc` like the backup workflow writes it."""
    result = subprocess.run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-pass",
            f"env:{key}",
            "-in",
            str(source),
            "-out",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"decryption failed: {result.stderr.strip()[:400]}")
    return target


def _counts(dsn: str, tables: tuple[str, ...]) -> dict[str, int]:
    import asyncio

    import asyncpg

    async def body():
        conn = await asyncpg.connect(dsn)
        try:
            out = {}
            for table in tables:
                exists = await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                )
                if not exists:
                    continue
                out[table] = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            return out
        finally:
            await conn.close()

    return asyncio.run(body())


def _serves(dsn: str) -> dict:
    """The dashboard's own aggregate, run against the restored database.

    A restore that counts right but cannot answer `/api/stats` is still a failed drill, so
    this calls the exact query the API calls rather than a lookalike.
    """
    import asyncio

    import asyncpg

    from server.queries import get_stats

    async def body():
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            return await get_stats(pool)
        finally:
            await pool.close()

    return asyncio.run(body())


def _create_database(dsn: str, name: str) -> None:
    # `createdb` needs a maintenance database and the same credentials as the source.
    result = subprocess.run(
        [tool("createdb"), "--maintenance-db", _with_database(dsn, "postgres"), name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and "already exists" not in result.stderr:
        raise SystemExit(f"createdb failed: {result.stderr.strip()[:300]}")


def _drop_database(dsn: str, name: str) -> None:
    subprocess.run(
        [
            tool("dropdb"),
            "--if-exists",
            "--force",
            "--maintenance-db",
            _with_database(dsn, "postgres"),
            name,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def drill(source_dsn: str, dump: Path | None, timeout_s: float = 300.0) -> dict:
    """Run the whole drill and return what happened, or raise on any surprise."""
    source = _database(source_dsn)
    scratch = f"{source}{DRILL_SUFFIX}"
    started = time.perf_counter()
    workdir = Path(tempfile.mkdtemp(prefix="finscrape-drill-"))
    archive = workdir / "drill.dump"

    if dump is None:
        result = subprocess.run(
            [tool("pg_dump"), "-Fc", "--no-owner", "-f", str(archive), source_dsn],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            raise SystemExit(f"pg_dump failed: {result.stderr.strip()[:400]}")
    elif dump.suffix == ".enc":
        key = os.getenv("BACKUP_KEY", "")
        if not key:
            raise SystemExit("BACKUP_KEY is required to decrypt an .enc dump")
        decrypt(dump, key, archive)
    else:
        archive = dump

    entries = verify_dump(archive)
    before = _counts(source_dsn, CRITICAL_TABLES)

    _create_database(source_dsn, scratch)
    try:
        restore = subprocess.run(
            [
                tool("pg_restore"),
                "--no-owner",
                "--no-privileges",
                "-d",
                _with_database(source_dsn, scratch),
                str(archive),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
        # pg_restore exits 1 for "warnings" (role grants, comments). Anything else is fatal,
        # and a missing table is caught by the count comparison below either way.
        if restore.returncode > 1:
            raise SystemExit(f"pg_restore failed: {restore.stderr.strip()[:400]}")
        scratch_dsn = _with_database(source_dsn, scratch)
        after = _counts(scratch_dsn, CRITICAL_TABLES)
        served = _serves(scratch_dsn)
        elapsed = time.perf_counter() - started
    finally:
        _drop_database(source_dsn, scratch)

    mismatches = [
        f"{table}: source {before.get(table, 0)} != restored {after.get(table, 0)}"
        for table in CRITICAL_TABLES
        if before.get(table, 0) != after.get(table, 0)
    ]
    if mismatches:
        raise SystemExit("restore changed the data:\n  " + "\n  ".join(mismatches))
    if not served or "total_events" not in served:
        raise SystemExit(f"the restored database cannot answer /api/stats: {served!r}")
    return {
        "source": source,
        "scratch": scratch,
        "archive_entries": entries,
        "rows": after,
        "dashboard_total": served["total_events"],
        "seconds": round(elapsed, 1),
        "run_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def render(outcome: dict) -> str:
    rows = ", ".join(f"{table} {count}" for table, count in outcome["rows"].items())
    return (
        f"| {outcome['run_at']} | {outcome['source']} | {outcome['archive_entries']} objects | "
        f"{outcome['seconds']} s | /api/stats total_events={outcome['dashboard_total']} | {rows} |"
    )


def record(outcome: dict, doc: Path = RUNBOOK) -> None:
    """Append the row to the drill table — not to the end of the file.

    The runbook has sections after that table (secret rotation, retention), and a history
    line landing under the wrong heading is how a table stops being read.
    """
    header = (
        "| run (UTC) | source | archive | restore time | app check | rows verified |"
    )
    lines = doc.read_text(encoding="utf-8").splitlines()
    if header not in lines:
        raise SystemExit("docs/RUNBOOK.md has no restore-drill table to append to")
    end = lines.index(header)
    while end + 1 < len(lines) and lines[end + 1].startswith("|"):
        end += 1
    lines.insert(end + 1, render(outcome))
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source", default="", help="DSN to drill (default: the *_test URL)"
    )
    parser.add_argument(
        "--dump", default="", help="existing dump (.dump or .enc) to restore"
    )
    parser.add_argument(
        "--timeout", type=float, default=300.0, help="seconds per pg command"
    )
    parser.add_argument(
        "--record", action="store_true", help="append the result to the runbook"
    )
    args = parser.parse_args(argv)

    source_dsn = args.source or _source_dsn()
    if not _database(source_dsn).endswith("_test") and not args.source:
        parser.error(
            "refusing to drill against a database that is not named *_test — pass --source to override"
        )
    dump = Path(args.dump) if args.dump else None
    outcome = drill(source_dsn, dump, args.timeout)
    print(
        f"restore drill: {outcome['scratch']} from {outcome['archive_entries']} archive objects"
    )
    for table, count in outcome["rows"].items():
        print(f"  {table:20} {count:>8} rows")
    print(f"restore drill: /api/stats total_events={outcome['dashboard_total']}")
    print(f"restore drill: {outcome['seconds']} s")
    if args.record:
        record(outcome)
        print(f"restore drill: recorded in {RUNBOOK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
