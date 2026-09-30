"""Publish a Laya checkpoint for the ingest Action: a GitHub release holding laya.tar,
named in the repo variable LAYA_RELEASE that .github/workflows/ingest.yml reads.

    python scripts/laya_train/publish.py [CHECKPOINT_DIR]   (default ~/laya-ft/current)

The base model is Apache-2.0 and the training data is public headlines, so the
release is public. Older laya-* releases beyond the newest two are deleted.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

KEEP = 2


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout


def publish(checkpoint: Path) -> str:
    if not (checkpoint / "model.safetensors").exists():
        raise SystemExit(f"no model.safetensors under {checkpoint}")
    tag = "laya-" + datetime.now(UTC).strftime("%Y%m%d-%H%M")
    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "laya.tar"
        with tarfile.open(tar, "w") as t:
            for p in checkpoint.rglob("*"):
                if p.is_file():
                    t.add(p, arcname=p.relative_to(checkpoint).as_posix())
        gh(
            "release",
            "create",
            tag,
            str(tar),
            "--title",
            tag,
            "--latest=false",
            "--notes",
            "Laya sector/direction checkpoint for the ingest Action.",
        )
    gh("variable", "set", "LAYA_RELEASE", "--body", tag)
    tags = sorted(
        t
        for t in gh(
            "release",
            "list",
            "--limit",
            "100",
            "--json",
            "tagName",
            "--jq",
            ".[].tagName",
        ).split()
        if t.startswith("laya-")
    )
    for old in tags[:-KEEP]:
        gh("release", "delete", old, "--yes", "--cleanup-tag")
    return tag


if __name__ == "__main__":
    home = Path(os.environ.get("LAYA_FT_HOME", Path.home() / "laya-ft"))
    print(publish(Path(sys.argv[1]) if len(sys.argv) > 1 else home / "current"))
