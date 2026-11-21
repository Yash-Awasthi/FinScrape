"""Operational proof (plan M2.5): the backup restores, the alert fires, the load is known.

These are the checks that turn "we have backups" and "it should hold 50 rps" into
statements with a command and a number behind them.

* a failed dump is removed rather than uploaded, and an unreadable archive is refused;
* the restore drill compares row counts and runs the API's own aggregate on the copy;
* `scripts/check_prod.py` exits non-zero when no event landed in the window;
* the load test reports a p95 per endpoint and names the bottleneck.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from scripts import db_backup, loadtest, pg, restore_drill

ROOT = Path(__file__).resolve().parents[1]
BACKUP_WORKFLOW = ROOT / ".github" / "workflows" / "backup.yml"


# ------------------------------------------------------------------- a dump that failed


def test_an_empty_file_is_not_a_backup(tmp_path):
    empty = tmp_path / "worldfin.dump"
    empty.write_bytes(b"")
    with pytest.raises(pg.DumpError, match="empty"):
        pg.verify_dump(empty)


def test_a_truncated_archive_is_refused(tmp_path):
    """`test -s` passes on this file; the archive reader does not."""
    truncated = tmp_path / "worldfin.dump"
    truncated.write_bytes(b"PGDMP garbage" + b"\x00" * 64)
    with pytest.raises(pg.DumpError, match="not a readable archive"):
        pg.verify_dump(truncated)


def test_a_failed_dump_leaves_nothing_to_upload(tmp_path, monkeypatch):
    """The artifact step must have no partial file to pick up."""
    monkeypatch.setattr(db_backup, "BACKUP_DIR", tmp_path)

    def half_write(cmd, *args, **kwargs):
        # pg_dump dies mid-write: a plausible-looking partial file exists.
        target = Path(cmd[cmd.index("-f") + 1])
        target.write_bytes(b"PGDMP partial")
        raise RuntimeError("pg_dump: connection lost")

    monkeypatch.setattr(db_backup.subprocess, "run", half_write)
    with pytest.raises(RuntimeError):
        db_backup.backup()
    assert list(tmp_path.glob("worldfin-*.dump")) == [], "a partial dump was left behind"


def test_the_backup_workflow_verifies_before_it_uploads():
    text = BACKUP_WORKFLOW.read_text(encoding="utf-8")
    assert "pg_restore --list" in text, "the dump is never read back before upload"
    assert "cmp worldfin.dump roundtrip.dump" in text, "the encrypted round trip is untested"
    assert "if-no-files-found: error" in text
    # A failed dump has to fail the job: an `if: always()` upload would ship the wreckage.
    upload = text.split("upload-artifact", 1)[1]
    assert "if:" not in upload, "the artifact step must not run on failure"


# --------------------------------------------------------------------- the restore drill


def test_the_drill_refuses_a_database_that_is_not_a_test_copy():
    argv = ["--source", "postgresql://u:p@h:5432/worldfin"]
    with pytest.raises(SystemExit):
        restore_drill.main(argv)  # no --record, and not named *_test


def test_the_drill_renders_a_row_with_the_counts_that_matter():
    outcome = {
        "run_at": "2026-11-24T18:00:00Z",
        "source": "worldfin_test",
        "archive_entries": 90,
        "seconds": 1.8,
        "dashboard_total": 12,
        "rows": {"events": 12, "correlations": 3},
    }
    row = restore_drill.render(outcome)
    assert row.startswith("| 2026-11-24T18:00:00Z |")
    assert "total_events=12" in row and "events 12" in row


def test_the_runbook_has_a_drill_table_and_a_recorded_run():
    """A drill nobody wrote down is a drill nobody can compare the next one to."""
    text = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "| run (UTC) | source | archive | restore time | app check | rows verified |" in text
    history = [line for line in text.splitlines() if line.startswith("| 20")]
    assert history, "the drill table has no runs in it"
    assert any("total_events=" in line for line in history)


def test_restore_drill_checks_the_app_query_not_a_lookalike():
    source = Path(restore_drill.__file__).read_text(encoding="utf-8")
    assert "from server.queries import get_stats" in source
    assert "total_events" in source


# ------------------------------------------------------------------- the ingest alert


def _empty_db_and_event():
    from tests.server import PG_DSN, pg_reachable

    if not pg_reachable():
        pytest.skip("no Postgres for the alert test")
    return PG_DSN


def test_check_prod_fails_when_no_event_landed(monkeypatch):
    import asyncpg

    from scripts import check_prod

    dsn = _empty_db_and_event()

    async def empty():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("CREATE TABLE IF NOT EXISTS events (created_at TIMESTAMPTZ)")
            await conn.execute("TRUNCATE events CASCADE")
        finally:
            await conn.close()

    asyncio.run(empty())
    monkeypatch.setenv("WORLDFIN_DATABASE_URL", dsn)
    monkeypatch.delenv("INGEST_EVERY_HOURS", raising=False)
    assert asyncio.run(check_prod.main()) == 1


def test_check_prod_passes_when_a_fresh_event_exists(monkeypatch):
    import asyncpg

    from scripts import check_prod

    dsn = _empty_db_and_event()

    async def seeded():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("CREATE TABLE IF NOT EXISTS events (created_at TIMESTAMPTZ)")
            await conn.execute("TRUNCATE events CASCADE")
            await conn.execute(
                "INSERT INTO events (content_hash, subject, event_type, verdict, timestamp, created_at) "
                "VALUES ('operational-fresh', 'fresh', 'earnings', 'OBSERVE', now(), now())"
            )
        finally:
            await conn.close()

    asyncio.run(seeded())
    monkeypatch.setenv("WORLDFIN_DATABASE_URL", dsn)
    assert asyncio.run(check_prod.main()) == 0


def test_the_window_is_two_ingest_intervals_plus_one_hour():
    from scripts import check_prod

    assert check_prod.max_age_hours("24") == 49
    assert check_prod.max_age_hours("6") == 13
    assert check_prod.max_age_hours(None) == 49


# -------------------------------------------------------------------------- the load test


def _report() -> loadtest.Report:
    report = loadtest.Report(elapsed=10.0)
    for i in range(100):
        report.samples.append(loadtest.Sample(path="/api/events", ms=5.0 + i, status=200))
    for i in range(100):
        report.samples.append(loadtest.Sample(path="/api/market/quotes", ms=900.0, status=200))
    return report


def test_the_load_report_publishes_p95_per_endpoint_and_names_the_bottleneck():
    summary = _report().summary()
    assert summary["/api/events"]["p50_ms"] < summary["/api/events"]["p95_ms"]
    assert summary["/api/events"]["p99_ms"] >= summary["/api/events"]["p95_ms"]
    assert "/api/market/quotes is the bottleneck" in _report().bottleneck()


def test_a_fast_run_reports_no_bottleneck():
    report = loadtest.Report(elapsed=1.0)
    for i in range(50):
        report.samples.append(loadtest.Sample(path="/api/events", ms=4.0 + i, status=200))
    assert "no bottleneck at this rate" in report.bottleneck()


def test_a_server_error_is_counted_and_fails_the_run(tmp_path, monkeypatch, capsys):
    async def fake_drive(*args, **kwargs):
        report = loadtest.Report(elapsed=1.0)
        report.samples.append(loadtest.Sample(path="/api/events", ms=1.0, status=503))
        return report

    monkeypatch.setattr(loadtest, "drive", fake_drive)
    assert loadtest.main(["--base-url", "http://127.0.0.1:1"]) == 1
    assert "500" not in capsys.readouterr().out  # the summary, not the page


def test_the_base_url_must_be_absolute():
    with pytest.raises(SystemExit):
        loadtest.main(["--base-url", "127.0.0.1:8010"])


def test_the_load_numbers_are_written_down():
    doc = ROOT / "docs" / "LOAD.md"
    assert doc.is_file(), "the load test has no published result"
    text = doc.read_text(encoding="utf-8")
    assert "p95" in text and "bottleneck" in text.lower()
    assert "/api/market/quotes" in text


# ------------------------------------------------------------------------- cold start


def test_a_cold_start_within_the_quoted_number_passes():
    from scripts import warm

    assert "within the 50 s" in warm.verdict(12.0, budget=120, quoted=50)
    # The end-to-end spawn is `make warm`: booting a server inside the unit suite would make
    # the suite's runtime depend on this machine, which is exactly what the script measures.
    assert warm.main(["--base-url", "http://127.0.0.1:1", "--budget", "1"]) == 1


def test_a_slower_cold_start_fails_and_asks_for_a_keep_warm():
    from scripts import warm

    message = warm.verdict(75.0, budget=120, quoted=50)
    assert "above the 50 s" in message and "keep-warm" in message


def test_a_cold_start_that_never_answers_fails():
    from scripts import warm

    assert "no answer within 5 s" in warm.verdict(None, budget=5)


def test_the_keep_warm_workflow_has_no_schedule_of_its_own():
    text = (ROOT / ".github" / "workflows" / "warm.yml").read_text(encoding="utf-8")
    assert "scripts.warm" in text
    # A comment may mention it; a top-level trigger key must not exist.
    assert "\n  schedule:" not in text, "the cron Worker must stay the only scheduler"
    assert "workflow_dispatch" in text
