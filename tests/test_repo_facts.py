"""The facts script turns each tool's output into the number the docs quote.

Every parser is tested on a recorded sample so a tool's output format change shows up
here rather than as a silently stale README count.
"""

import json
from pathlib import Path

import pytest

from scripts import repo_facts

PYTEST_TAIL = """tests/test_a.py::test_one
tests/test_b.py::test_two

771 tests collected in 32.12s
"""

PYTEST_WITH_ERRORS = """tests/test_broken.py: error: import failed

12 tests collected, 1 error in 3.10s
"""

VP_LIST = """src/live.test.ts > poller > refreshes every 60 s
src/state.test.ts > store > keeps the last good data
"""

PW_LIST = """Listing tests:
  [chromium] › dashboard.spec.ts:152:1 › a test

Total: 8 tests in 1 file
"""

RUFF_CONCISE = """server/app.py:12:5: F401 [*] `os` imported but unused
server/app.py:14:9: E501 Line too long (120 > 100)
worker/main.py:3:1: UP035 [*] `typing.List` is deprecated
Found 3 errors.
[*] 2 fixable with `--fix` (2 unsafe fixes available with `--fix --unsafe-fixes`).
"""

DEPLOY_TABLE = """| Model | Valid JSON | Sector accuracy | p50 latency |
|---|---|---|---|
| `qwen3.8-flash:free` | 79% | 79.5% | 30 s (p90 82 s) |
| `mimo-v2.6-flash:free` | 96% | 66.7% | 14 s (p90 21 s) |
"""


def test_pytest_total_from_the_summary_line():
    assert repo_facts.count_pytest_tests(PYTEST_TAIL) == 771


def test_pytest_total_survives_a_collection_error():
    # A broken test file still reports how many tests exist; the count must not vanish.
    assert repo_facts.count_pytest_tests(PYTEST_WITH_ERRORS) == 12


def test_pytest_total_is_none_when_the_tool_said_nothing():
    assert repo_facts.count_pytest_tests("") is None
    assert repo_facts.count_pytest_tests("no tests ran") is None


def test_vitest_counts_test_lines_not_the_summary():
    assert repo_facts.count_vitest_tests(VP_LIST) == 2


def test_playwright_total_from_the_footer():
    assert repo_facts.count_playwright_tests(PW_LIST) == 8


def test_playwright_total_is_none_without_a_listing():
    assert repo_facts.count_playwright_tests("Error: no tests found") is None


def test_ruff_error_and_file_counts_skip_the_footer():
    errors, files = repo_facts.parse_ruff_concise(RUFF_CONCISE)
    assert (errors, files) == (3, 2)


def test_model_table_parses_into_rows(tmp_path):
    doc = tmp_path / "DEPLOY.md"
    doc.write_text(DEPLOY_TABLE, encoding="utf-8")
    rows = repo_facts.measured_model_rows(doc)
    assert rows["qwen3.8-flash:free"]["Sector accuracy"] == "79.5%"
    assert set(rows) == {"qwen3.8-flash:free", "mimo-v2.6-flash:free"}


def test_markdown_names_a_model_with_no_measured_row():
    facts = {
        **STUB,
        "models_configured": ["unmeasured-model:free"],
        "models_measured": {},
    }
    rendered = repo_facts.render_markdown(facts)
    assert "no measured row" in rendered
    assert "unmeasured-model:free" in rendered


def test_vendored_tree_is_excluded_from_every_count():
    tracked = repo_facts.tracked_python_files()
    assert tracked
    assert not any(p.startswith("finscrape/absorbed/") for p in tracked)


def test_counts_come_back_positive_from_the_real_repo():
    # The docs quote these; a zero means the walk broke, not that the repo is empty.
    assert repo_facts.test_function_count() > 500
    assert repo_facts.web_source_files() > 20


def test_json_mode_is_parseable(capsys, monkeypatch):
    monkeypatch.setattr(repo_facts, "collect", lambda root=None: {"python_files": 7})
    assert repo_facts.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"python_files": 7}


STUB = {
    "python_files": 3,
    "test_functions": 5,
    "pytest_tests": 11,
    "vitest_tests": 2,
    "playwright_tests": 1,
    "web_source_files": 4,
    "world_feeds": 37,
    "ticker_overlap": 25,
    "ruff_errors": 0,
    "ruff_files_with_errors": 0,
    "ruff_clean_files": 3,
    "ruff_files": 3,
    "models_configured": [],
    "models_measured": {},
    "errors": [],
}


def test_sentence_quotes_the_three_suites():
    assert repo_facts.render_sentence(STUB) == (
        "11 pytest cases, 2 Vitest tests and 1 Playwright spec; CI runs all of them. "
        "Counted by `python -m scripts.repo_facts`."
    )


def test_fill_block_rewrites_only_the_marked_region():
    text = "before\n<!-- facts:start -->\nold\n<!-- facts:end -->\nafter\n"
    filled = repo_facts.fill_block(text, "new")
    assert filled == "before\n<!-- facts:start -->\nnew\n<!-- facts:end -->\nafter\n"


def test_fill_block_refuses_a_doc_without_markers():
    # Silence here would let a doc quote numbers nothing updates.
    assert repo_facts.fill_block("no markers at all\n", "new") is None


def test_named_block_leaves_the_default_block_alone():
    text = (
        "<!-- facts:start -->\nkept\n<!-- facts:end -->\n"
        "and <!-- facts:start feeds -->\n1\n<!-- facts:end --> feeds\n"
    )
    assert repo_facts.fill_block(text, "37", "feeds") == (
        "<!-- facts:start -->\nkept\n<!-- facts:end -->\n"
        "and <!-- facts:start feeds -->\n37\n<!-- facts:end --> feeds\n"
    )
    assert repo_facts.fill_block(text, "kept", "default") == text


def test_render_count_is_a_bare_number():
    assert repo_facts.render_count(STUB, "world_feeds") == "37"


def test_check_reports_drift_and_write_clears_it(tmp_path, monkeypatch):
    doc = tmp_path / "README.md"
    doc.write_text(
        "<!-- facts:start -->\nstale\n<!-- facts:end -->\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        repo_facts, "BLOCKS", {("README.md", "default"): repo_facts.render_sentence}
    )
    assert repo_facts.sync_docs(STUB, write=False, root=tmp_path) == ["README.md"]
    assert repo_facts.sync_docs(STUB, write=True, root=tmp_path) == ["README.md"]
    assert repo_facts.sync_docs(STUB, write=False, root=tmp_path) == []
    assert "11 pytest cases" in doc.read_text(encoding="utf-8")


def test_a_doc_without_markers_is_reported_as_stale(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("nothing marked\n", encoding="utf-8")
    monkeypatch.setattr(
        repo_facts, "BLOCKS", {("README.md", "default"): repo_facts.render_markdown}
    )
    problems = repo_facts.sync_docs(STUB, write=True, root=tmp_path)
    assert problems and "marker" in problems[0]


def test_the_real_docs_are_in_sync():
    # This is the CI gate's assertion: a hand-edited count fails here first.
    # Two of the counts come from the web CLIs, so the comparison needs `npm ci`
    # in web/; the docs-drift job installs them, a plain pytest run does not.
    web_bin = (
        Path(repo_facts.__file__).resolve().parents[1] / "web" / "node_modules" / ".bin"
    )
    if not web_bin.is_dir():
        pytest.skip("web dependencies are not installed")
    assert repo_facts.sync_docs(repo_facts.collect(), write=False) == []


def test_check_mode_exits_nonzero_on_drift(monkeypatch, capsys):
    # This exit code is what makes the CI `docs-drift` job fail instead of printing.
    monkeypatch.setattr(repo_facts, "collect", lambda root=None: dict(STUB))
    monkeypatch.setattr(
        repo_facts, "sync_docs", lambda facts, write, root=None: ["README.md"]
    )
    assert repo_facts.main(["--check"]) == 1
    assert "stale facts block: README.md" in capsys.readouterr().err


def test_write_mode_exits_zero_after_fixing(monkeypatch):
    monkeypatch.setattr(repo_facts, "collect", lambda root=None: dict(STUB))
    monkeypatch.setattr(
        repo_facts, "sync_docs", lambda facts, write, root=None: ["README.md"]
    )
    assert repo_facts.main(["--write"]) == 0
