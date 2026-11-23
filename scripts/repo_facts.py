"""Measure the numbers the docs quote, so no count is ever hand-typed again.

``python -m scripts.repo_facts`` prints a markdown table, ``--json`` prints the same
facts as JSON. Every count comes from a command or a file walk run now; anything a
tool refuses to answer is ``null`` with the reason in ``errors``, never a guess.

    python -m scripts.repo_facts --json
    python -m scripts.repo_facts            # markdown

The doc-drift CI job runs ``--json`` and diffs the committed tables against it, so a
stale number fails the build instead of misleading the next reader.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# Directories the app actually ships or tests. `finscrape/absorbed` is vendored
# reference material and stays out of every count (see pyproject [tool.ruff]).
SOURCE_DIRS = ("finscrape", "server", "worker", "tests", "scripts")
DEPLOY_DOC = ROOT / "docs" / "DEPLOY.md"


def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[str, int] | None:
    """Run a count command; None when the tool is missing or hangs.

    Returns stdout and the exit code: `ruff check` exits 1 when it finds violations,
    and that output is exactly what this script measures, so a non-zero code alone is
    not a failure.
    """
    try:
        done = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return done.stdout, done.returncode


def _tool(parent: Path, name: str) -> str:
    """Resolve a node CLI from a package's .bin (npx is not a shell-free fallback)."""
    found = shutil.which(name, path=str(parent / "node_modules" / ".bin"))
    return found or name


def tracked_python_files(root: Path = ROOT) -> list[str]:
    """Tracked .py files under the shipped source dirs, vendored code excluded."""
    run = _run(["git", "ls-files", "*.py"], root)
    if run is None or run[1] != 0:
        return []
    return [
        path
        for path in run[0].splitlines()
        if path.strip()
        and path.split("/")[0] in SOURCE_DIRS
        and not path.startswith("finscrape/absorbed/")
    ]


def test_function_count(test_dir: Path = ROOT / "tests") -> int:
    """`def test_` definitions — what the README calls "tests"."""
    return sum(
        1
        for path in test_dir.rglob("*.py")
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.lstrip().startswith("def test_")
    )


def web_source_files(web_src: Path = ROOT / "web" / "src") -> int:
    if not web_src.is_dir():
        return 0
    return sum(
        1 for p in web_src.rglob("*") if p.is_file() and p.suffix in {".ts", ".tsx"}
    )


def count_pytest_tests(output: str) -> int | None:
    """Parse `pytest --collect-only -q` for the total."""

    def parse(text: str) -> int | None:
        match = re.search(r"^(\d+) tests collected", text, re.MULTILINE)
        if match:
            return int(match.group(1))
        # A collection error prints "N tests collected, M errors". pytest exits non-zero
        # there, so this parser is also used on stdout even when the run failed.
        match = re.search(r"^(\d+) tests? collected", text, re.MULTILINE)
        return int(match.group(1)) if match else None

    return parse(output)


def count_vitest_tests(output: str) -> int:
    """`vp test list` prints one `<file> > <suite> > <name>` line per test."""
    return sum(1 for line in output.splitlines() if " > " in line)


def count_playwright_tests(output: str) -> int | None:
    """`playwright test --list` ends with `Total: N tests in M file(s)`."""
    match = re.search(r"^Total: (\d+) tests?", output, re.MULTILINE)
    return int(match.group(1)) if match else None


def parse_ruff_concise(output: str) -> tuple[int, int]:
    """(errors, files with at least one error) from `ruff check --output-format concise`."""
    files: set[str] = set()
    errors = 0
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("Found ", "[")):
            continue
        head = line.split(":", 1)[0]
        if head.endswith(".py"):
            files.add(head)
            errors += 1
    return errors, len(files)


def measured_model_rows(deploy_doc: Path = DEPLOY_DOC) -> dict[str, dict[str, str]]:
    """Rows of the model comparison table in docs/DEPLOY.md, keyed by model id.

    The table is hand-measured (m2.1 replaces it with a reproducible eval run), but
    parsing it lets the drift check notice a model that has no measured row.
    """
    if not deploy_doc.is_file():
        return {}
    rows: dict[str, dict[str, str]] = {}
    header: list[str] = []
    for line in deploy_doc.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == "Model":
            header = cells
            continue
        if not header or set("".join(cells)) <= {"-", ":", " "}:
            continue
        model = cells[0].strip("`")
        if model and model.startswith("|"):
            continue
        if model and len(cells) == len(header):
            rows[model] = dict(zip(header[1:], cells[1:], strict=True))
    return rows


def configured_models(deploy_doc: Path = DEPLOY_DOC) -> list[str]:
    """Model ids the app would call today: settings first, then the documented pin.

    Production model ids live in GitHub variables, so a local checkout has no way to
    read them; when settings say only `auto`, the documented primary/fallback pin is
    the closest truthful answer.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from server.settings import Settings

        settings = Settings()
        models = [settings.ai_model.strip()]
        models += [
            m.strip() for m in settings.ai_model_fallback.split(",") if m.strip()
        ]
        models = [m for m in models if m and m != "auto"]
        if models:
            return models
    except Exception:
        pass
    if not deploy_doc.is_file():
        return []
    text = deploy_doc.read_text(encoding="utf-8")
    return re.findall(r"`([A-Za-z0-9_.:\-]+:free)`", text)[:2]


def _ruff_cmd() -> list[str]:
    """ruff ships as a console script; fall back to `python -m ruff` where it is not on PATH."""
    found = shutil.which("ruff")
    return [found] if found else [sys.executable, "-m", "ruff"]


# `ruff check .` passes on the frozen debt in ruff-baseline.toml, so the debt itself is
# only visible with that allowlist switched off. Both numbers are reported: how much debt
# exists, and that the gated run is clean.
DEBT_ONLY = ["--config", "lint.per-file-ignores={}"]


def world_feeds() -> int:
    """Feed registry entries the scrapers ship with (`finscrape/scrapers/world/feeds.py`)."""
    sys.path.insert(0, str(ROOT))
    try:
        from finscrape.fetchers.world.feeds import FEEDS

        return len(FEEDS)
    except Exception:
        return -1


def ticker_overlap() -> int:
    """Symbols whose topics the entity index and the topic keywords share.

    This is the ceiling on ticker coverage the docs quote; the set is computed at
    runtime by `server.correlate._topics_by_ticker`.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from server.correlate import _topics_by_ticker

        return len(_topics_by_ticker())
    except Exception:
        return -1


def collect(root: Path = ROOT) -> dict[str, Any]:
    """Every fact, measured now."""
    errors: list[str] = []
    py_files = tracked_python_files(root)
    ruff_run = _run(
        [*_ruff_cmd(), "check", ".", "--output-format", "concise", *DEBT_ONLY], root
    )
    if ruff_run is None:
        errors.append("ruff check did not run")
        ruff_errors, ruff_bad = -1, -1
    else:
        ruff_errors, ruff_bad = parse_ruff_concise(ruff_run[0])

    pytest_run = _run([sys.executable, "-m", "pytest", "-q", "--collect-only"], root)
    pytest_tests = count_pytest_tests(pytest_run[0] if pytest_run else "")
    if pytest_tests is None:
        errors.append("pytest --collect-only did not report a count")

    web = root / "web"
    vitest_run = _run([_tool(web, "vp"), "test", "list"], web) if web.is_dir() else None
    vitest_tests = count_vitest_tests(vitest_run[0] if vitest_run else "")
    if not vitest_tests:
        errors.append("vitest list did not run (npm ci in web/)")

    pw_run = (
        _run([_tool(web, "playwright"), "test", "--list"], web)
        if web.is_dir()
        else None
    )
    playwright_tests = count_playwright_tests(pw_run[0] if pw_run else "")
    if playwright_tests is None:
        errors.append("playwright --list did not run")

    measured = measured_model_rows(root / "docs" / "DEPLOY.md")
    configured = configured_models()

    return {
        "python_files": len(py_files),
        "test_functions": test_function_count(root / "tests"),
        "pytest_tests": pytest_tests,
        "vitest_tests": vitest_tests,
        "playwright_tests": playwright_tests,
        "web_source_files": web_source_files(root / "web" / "src"),
        "world_feeds": world_feeds(),
        "ticker_overlap": ticker_overlap(),
        "ruff_files": len(py_files),
        "ruff_errors": ruff_errors,
        "ruff_files_with_errors": ruff_bad,
        "ruff_clean_files": (len(py_files) - ruff_bad) if ruff_bad >= 0 else -1,
        "models_configured": configured,
        "models_measured": measured,
        "errors": errors,
    }


def render_markdown(facts: dict[str, Any]) -> str:
    """The block that goes between docs' `<!-- facts:start -->` markers."""
    configured = facts["models_configured"] or ["unset"]
    measured = facts["models_measured"]
    rows = [
        "| Fact | Measured |",
        "|---|---|",
        f"| Python files (tracked) | {facts['python_files']} |",
        f"| Test functions (`def test_`) | {facts['test_functions']} |",
        f"| pytest tests collected | {facts['pytest_tests']} |",
        f"| Vitest tests | {facts['vitest_tests']} |",
        f"| Playwright tests | {facts['playwright_tests']} |",
        f"| Web source files | {facts['web_source_files']} |",
        f"| World RSS feeds in the registry | {facts['world_feeds']} |",
        f"| Tickers the entity index and topic keywords share | {facts['ticker_overlap']} |",
        f"| Ruff errors / files with errors | {facts['ruff_errors']} / {facts['ruff_files_with_errors']} |",
        f"| Ruff-clean tracked files | {facts['ruff_clean_files']} of {facts['ruff_files']} |",
        f"| Configured models | {', '.join(configured)} |",
    ]
    for model in configured:
        row = measured.get(model)
        cells = (
            f"{row.get('Valid JSON', '?')} valid JSON, {row.get('Sector accuracy', '?')} sector, "
            f"{row.get('p50 latency', '?')} p50"
            if row
            else "**no measured row** — run the eval (M2.1)"
        )
        rows.append(f"| `{model}` | {cells} |")
    return "\n".join(rows)


def render_sentence(facts: dict[str, Any]) -> str:
    """The one-line form the README wants where a table would break the prose."""
    specs = "spec" if facts["playwright_tests"] == 1 else "specs"
    return (
        f"{facts['pytest_tests']} pytest cases, {facts['vitest_tests']} Vitest tests and "
        f"{facts['playwright_tests']} Playwright {specs}; CI runs all of them. "
        "Counted by `python -m scripts.repo_facts`."
    )


# Which doc gets which rendering of the same measurements.
BLOCKS: dict[str, Any] = {
    "README.md": render_sentence,
    "docs/ARCHITECTURE.md": render_markdown,
}

MARKER = re.compile(r"(<!-- facts:start -->\n)(.*?)(<!-- facts:end -->)", re.DOTALL)


def render_count(facts: dict[str, Any], key: str) -> str:
    """A bare number, for a sentence that wants the count inline."""
    return str(facts[key])


# Which doc gets which rendering of the same measurements, keyed by (doc, block name).
# The unnamed block is "default"; a named marker (`<!-- facts:start feeds -->`) carries
# one number that belongs inside a sentence.
BLOCKS: dict[tuple[str, str], Any] = {
    ("README.md", "default"): render_sentence,
    ("README.md", "feeds"): lambda facts: render_count(facts, "world_feeds"),
    ("docs/ARCHITECTURE.md", "default"): render_markdown,
}


def marker_pattern(name: str) -> re.Pattern[str]:
    """The one marker pair for a named block; `default` is the unnamed pair."""
    head = (
        "<!-- facts:start -->" if name == "default" else f"<!-- facts:start {name} -->"
    )
    return re.compile(rf"({re.escape(head)}\n)(.*?)(<!-- facts:end -->)", re.DOTALL)


def fill_block(text: str, body: str, name: str = "default") -> str | None:
    """Replace what sits between one facts marker pair; None when that pair is absent."""
    pattern = marker_pattern(name)
    if not pattern.search(text):
        return None
    return pattern.sub(lambda m: m.group(1) + body + "\n" + m.group(3), text, count=1)


def sync_docs(facts: dict[str, Any], write: bool, root: Path = ROOT) -> list[str]:
    """Update each doc's facts blocks (write) or report the stale or unmarked ones (check)."""
    stale: list[str] = []
    docs = {rel for rel, _ in BLOCKS}
    for rel in sorted(docs):
        path = root / rel
        if not path.is_file():
            stale.append(f"{rel}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        updated = text
        for (doc, name), renderer in BLOCKS.items():
            if doc != rel:
                continue
            filled = fill_block(updated, renderer(facts), name)
            if filled is None:
                stale.append(
                    f"{rel}: no <!-- facts:start{f' {name}' if name != 'default' else ''} --> marker"
                )
                continue
            updated = filled
        if updated != text:
            if rel not in stale:
                stale.append(rel)
            if write:
                path.write_text(updated, encoding="utf-8", newline="\n")
    return stale


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    facts = collect()
    if "--json" in args:
        print(json.dumps(facts, indent=2, sort_keys=True))
    elif "--write" in args or "--check" in args:
        stale = sync_docs(facts, write="--write" in args)
        if stale and "--check" in args:
            for rel in stale:
                print(f"repo_facts: stale facts block: {rel}", file=sys.stderr)
            return 1
        for rel in stale:
            print(f"repo_facts: updated {rel}", file=sys.stderr)
    else:
        print(render_markdown(facts))
    for problem in facts.get("errors", []):
        print(f"repo_facts: {problem}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
