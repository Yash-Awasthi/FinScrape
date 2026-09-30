"""Guards that multi_model / analyze_batch / batch prompts stay deleted."""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def scan_references(root: Path) -> list[str]:
    """Scan first-party Python, failing closed on traversal or decoding errors."""
    excluded = {".venv", ".git", "reference", "absorbed", "node_modules"}
    pattern = re.compile(r"multi_model|analyze_batch|BATCH_ANALYSIS")
    hits = []

    def fail(error):
        raise error

    for directory, directories, files in os.walk(root, onerror=fail):
        directories[:] = sorted(name for name in directories if name not in excluded)
        for name in sorted(files):
            if not name.endswith(".py") or name == "test_no_multi_model.py":
                continue
            path = Path(directory) / name
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(root).as_posix()}:{number}:{line}")
    return hits


def test_reference_scan_reports_matches_and_retains_exclusions(tmp_path):
    (tmp_path / "source.py").write_text("# clean\nanalyze_batch()\n", encoding="utf-8")
    for name in (".venv", ".git", "reference", "absorbed", "node_modules"):
        directory = tmp_path / "nested" / name
        directory.mkdir(parents=True)
        (directory / "excluded.py").write_text("multi_model", encoding="utf-8")
    (tmp_path / "test_no_multi_model.py").write_text("multi_model", encoding="utf-8")
    (tmp_path / "readme.md").write_text("BATCH_ANALYSIS", encoding="utf-8")
    assert scan_references(tmp_path) == ["source.py:2:analyze_batch()"]


def test_reference_scan_surfaces_invalid_source_encoding(tmp_path):
    (tmp_path / "invalid.py").write_bytes(b"\xff")
    with pytest.raises(UnicodeError):
        scan_references(tmp_path)


def test_reference_scan_surfaces_missing_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_references(tmp_path / "missing")


def test_no_multi_model_references_in_source():
    hits = scan_references(REPO_ROOT)
    assert hits == [], "stale references found:\n" + "\n".join(hits)


def test_multi_model_module_deleted():
    assert not (REPO_ROOT / "finscrape" / "analysis" / "multi_model.py").exists()


def test_analyze_batch_not_exported():
    from finscrape import analysis

    assert not hasattr(analysis, "analyze_batch")


def test_batch_prompt_constants_removed():
    from finscrape.analysis import prompts

    assert not hasattr(prompts, "BATCH_SYSTEM_PROMPT")
    assert not hasattr(prompts, "BATCH_ANALYSIS_PROMPT")
