"""Postgres client helpers shared by the backup, restore and drill scripts.

One place for "where is pg_dump" and for the check that separates *a file* from *a backup*:
`pg_restore --list` has to be able to read the archive. A truncated dump passes `-s` and
fails on the restore, which is the worst possible moment to find out.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def tool(name: str) -> str:
    """`pg_dump`, `pg_restore`, `createdb` — from PATH, PG_BIN, or the Windows install."""
    found = shutil.which(name)
    if found:
        return found
    directories = [os.getenv("PG_BIN", "")]
    root = Path(os.getenv("ProgramFiles", "C:/Program Files")) / "PostgreSQL"
    if root.is_dir():
        directories += [str(p / "bin") for p in sorted(root.iterdir(), reverse=True)]
    for directory in filter(None, directories):
        for candidate in (Path(directory) / name, Path(directory) / f"{name}.exe"):
            if candidate.exists():
                return str(candidate)
    raise SystemExit(f"{name} not found: add it to PATH or set PG_BIN")


class DumpError(RuntimeError):
    """The archive is not a readable pg_dump file."""


def verify_dump(path: Path) -> int:
    """Return the number of archive entries, or raise `DumpError`."""
    if not path.is_file():
        raise DumpError(f"no dump at {path}")
    if path.stat().st_size == 0:
        raise DumpError(f"{path} is empty — an empty file is not a backup")
    result = subprocess.run(
        [tool("pg_restore"), "--list", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DumpError(
            f"{path} is not a readable archive: {result.stderr.strip()[:400]}"
        )
    entries = [
        line for line in result.stdout.splitlines() if line and not line.startswith(";")
    ]
    if not entries:
        raise DumpError(f"{path} lists no objects")
    return len(entries)
