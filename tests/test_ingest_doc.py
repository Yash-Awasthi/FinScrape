"""The ingest state machine stays documented (plan M3.4).

A diagram nobody updates is worse than none, so this pins the two things that rot
silently: every stage that exists in `Worker.run_source` has a row with a failure path,
and the document is reachable from the README.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "INGEST.md"

STAGES = (
    "fetch",
    "visited dedup",
    "relevance gate",
    "analysis",
    "validate + tickers",
    "score",
    "dedup",
    "persist",
    "correlate",
    "notify",
    "health",
)


def test_every_stage_has_a_row_and_a_failure_path() -> None:
    text = DOC.read_text(encoding="utf-8")
    for stage in STAGES:
        assert f"**{stage}**" in text, stage
    # One "On failure" column header: the failure path is documented per stage, not
    # as a paragraph at the bottom that a future stage would not be added to.
    assert text.count("On failure") == 1


def test_the_diagram_is_in_the_document_and_linked_from_the_readme() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "```mermaid" in text and "flowchart TD" in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/INGEST.md" in readme
