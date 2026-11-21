"""No credential is tracked, and `.env` cannot be committed (plan M1.6).

The throwaway keys named in `notes.md` are rotated by the owner — that part cannot be
tested from here. What can be, and is, is that the repository never carries one: `.env`
is ignored, nothing named `.env` is tracked, and `.env.example` holds placeholders only.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A value that looks like a live credential rather than a placeholder.
REAL_SECRET = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9_-]{20,}"
    r"|AIza[A-Za-z0-9_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})"
)
SECRET_NAME = re.compile(r"[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*")
PLACEHOLDERS = (
    "",
    "ollama",
    "your_key_here",
    "local-dev-key",
    "admin",
    "changeme",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def test_env_is_git_ignored():
    out = _git("check-ignore", "-v", ".env")
    assert ".env" in out, "a .env in the tree would be committable"


def test_no_env_file_is_tracked():
    tracked = [p for p in _git("ls-files").splitlines() if Path(p).name == ".env"]
    assert tracked == []


def test_env_example_holds_placeholders_only():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    offenders = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        value = value.split("#", 1)[0].strip().strip("'\"")
        if not SECRET_NAME.match(name.strip()):
            continue
        if REAL_SECRET.search(value):
            offenders.append(name.strip())
        # An empty value is fine; a documented placeholder is fine; anything else is a
        # credential in a file that ships with the repository.
        elif value and value not in PLACEHOLDERS and "/" not in value and ":" not in value:
            offenders.append(f"{name.strip()}={value}")
    assert not offenders, offenders


def test_the_history_carries_no_live_looking_key():
    # One pass over every blob in every commit: cheap here (~140 commits), and it is the
    # only way to catch a key that was added and deleted again.
    revs = _git("rev-list", "--all").split()
    if not revs:
        return
    found = subprocess.run(
        ["git", "grep", "-hoE", REAL_SECRET.pattern, *revs],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert found.strip() == "", sorted(set(found.split()))[:5]
