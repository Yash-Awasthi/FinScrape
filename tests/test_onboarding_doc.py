"""The onboarding walkthrough stays honest (plan M3.5).

A fresh clone is the one path every contributor takes, so it is gated like code: eight
numbered steps, and every relative link resolves (a moved doc must not strand a reader
at step 8).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ONBOARDING.md"


def test_eight_numbered_steps() -> None:
    headings = re.findall(r"^## (\d+)\.", DOC.read_text(encoding="utf-8"), re.MULTILINE)
    assert headings == [str(n) for n in range(1, 9)]


def test_every_step_says_what_you_should_see() -> None:
    text = DOC.read_text(encoding="utf-8")
    steps = re.split(r"^## \d+\.", text, flags=re.MULTILINE)[1:]
    for index, step in enumerate(steps, 1):
        assert "Expected" in step, f"step {index} has no expected output"
        # A step is either a command, a URL, or a UI instruction ("view", "open").
        assert any(marker in step for marker in ("```", "http", "view")), (
            f"step {index} has no command or URL"
        )


def test_relative_links_resolve() -> None:
    text = DOC.read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)#:]+\.md)\)", text):
        assert (DOC.parent / target).is_file(), target


def test_it_is_linked_from_the_readme() -> None:
    assert "docs/ONBOARDING.md" in (ROOT / "README.md").read_text(encoding="utf-8")
