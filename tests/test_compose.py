"""A fresh clone must start with `make demo`: compose may only read tracked files."""

import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent


def test_compose_reads_only_tracked_files():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    )
    paths = [s["file"].removeprefix("./") for s in (compose.get("secrets") or {}).values()]
    for svc in compose["services"].values():
        build = svc.get("build")
        if build:
            ctx = build["context"].removeprefix("./").removeprefix(".")
            paths.append(f"{ctx}/{build['dockerfile']}".lstrip("/"))
    assert paths, "expected build files to check"
    assert [p for p in paths if p not in tracked] == []
