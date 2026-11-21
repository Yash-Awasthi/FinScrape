"""Dump or restore the FinScrape Postgres database.

    python scripts/db_backup.py backup            # backups/worldfin-<utc>.dump
    python scripts/db_backup.py restore <file>    # replaces current contents

Uses WORLDFIN_DATABASE_URL (from the environment or .env). pg_dump/pg_restore are
found on PATH, then in PG_BIN, then in the default Windows install location.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from scripts.pg import tool, verify_dump

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "backups"
KEEP = int(os.getenv("WORLDFIN_BACKUP_KEEP", "14"))


def _dsn() -> str:
    dsn = os.getenv("WORLDFIN_DATABASE_URL")
    env_file = ROOT / ".env"
    if not dsn and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("WORLDFIN_DATABASE_URL="):
                dsn = line.split("=", 1)[1].strip()
    return dsn or "postgresql://worldfin:worldfin@localhost:5432/worldfin"


def _tool(name: str) -> str:
    return tool(name)


def backup(max_age_days: int = 1) -> Path:
    """Write a dump and *verify* it before calling it a backup.

    A failed or truncated dump used to leave a file that looked like a backup; now the
    archive has to survive `pg_restore --list` and be younger than `max_age_days`, or the
    file is removed and the caller fails. Nothing partial is ever left behind for an
    upload step to pick up.
    """
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"worldfin-{stamp}.dump"
    try:
        subprocess.run([_tool("pg_dump"), "-Fc", "-f", str(out), _dsn()], check=True)
        verify_dump(out)
        verify_fresh(out, max_age_days)
    except Exception:
        out.unlink(missing_ok=True)  # never leave a partial dump where a backup belongs
        raise
    for old in sorted(BACKUP_DIR.glob("worldfin-*.dump"))[:-KEEP]:
        old.unlink()
    print(out)
    return out


def verify_fresh(path: Path, max_age_days: int = 1) -> None:
    """A dump that is older than the schedule means the schedule is not running."""
    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > max_age_days:
        raise RuntimeError(
            f"{path.name} is {age_days:.1f} days old, expected <= {max_age_days}"
        )


def restore(path: str) -> None:
    subprocess.run(
        [
            _tool("pg_restore"),
            "--clean",
            "--if-exists",
            "--no-owner",
            "-d",
            _dsn(),
            path,
        ],
        check=True,
    )


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "backup":
        backup()
    elif len(sys.argv) == 3 and sys.argv[1] == "restore":
        restore(sys.argv[2])
    else:
        sys.exit(__doc__)
