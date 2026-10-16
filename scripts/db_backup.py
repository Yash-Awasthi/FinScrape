"""Dump or restore the FinScrape Postgres database.

    python scripts/db_backup.py backup            # backups/worldfin-<utc>.dump
    python scripts/db_backup.py restore <file>    # replaces current contents

Uses WORLDFIN_DATABASE_URL (from the environment or .env). pg_dump/pg_restore are
found on PATH, then in PG_BIN, then in the default Windows install location.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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
    found = shutil.which(name)
    if found:
        return found
    dirs = [os.getenv("PG_BIN", "")]
    pg_root = Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"
    if pg_root.is_dir():
        dirs += [str(p / "bin") for p in sorted(pg_root.iterdir(), reverse=True)]
    for d in filter(None, dirs):
        for candidate in (Path(d) / name, Path(d) / f"{name}.exe"):
            if candidate.exists():
                return str(candidate)
    sys.exit(f"{name} not found: add it to PATH or set PG_BIN")


def backup() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"worldfin-{stamp}.dump"
    subprocess.run([_tool("pg_dump"), "-Fc", "-f", str(out), _dsn()], check=True)
    for old in sorted(BACKUP_DIR.glob("worldfin-*.dump"))[:-KEEP]:
        old.unlink()
    print(out)
    return out


def restore(path: str) -> None:
    subprocess.run(
        [_tool("pg_restore"), "--clean", "--if-exists", "--no-owner", "-d", _dsn(), path],
        check=True,
    )


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "backup":
        backup()
    elif len(sys.argv) == 3 and sys.argv[1] == "restore":
        restore(sys.argv[2])
    else:
        sys.exit(__doc__)
