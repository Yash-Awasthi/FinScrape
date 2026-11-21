"""Find modules under `finscrape/` that nothing imports (plan m1.2.3).

A file counts as dead when no other file names its module path — neither with an `import`
statement nor as a string, because the vendored tree resolves some names lazily through
`_LAZY_IMPORTS` tables. Entry points (CLI, package `__init__`, `__main__`) are never
candidates: nothing imports them and they are still the program.

    python -m scripts.dead_files            # report
    python -m scripts.dead_files --json     # machine-readable
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "finscrape"
# Never "dead": the package roots and any module a human runs directly.
ALWAYS_LIVE = {"__init__.py", "__main__.py", "cli.py", "manage.py"}


def tracked_python_files() -> list[Path]:
    """Every .py file under the repo that is not vendored-build output."""
    return [
        path
        for path in ROOT.rglob("*.py")
        if ".venv" not in path.parts
        and "node_modules" not in path.parts
        and "__pycache__" not in path.parts
        and ".git" not in path.parts
    ]


def module_name(path: Path) -> str:
    """`finscrape/engine/x.py` -> `finscrape.engine.x`."""
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def importers(module: str, sources: dict[Path, str], self_path: Path) -> list[Path]:
    """Files that name `module`, ignoring the file itself.

    Three ways a module gets referenced, all of which count:
    - the absolute path: `from a.b.c import x`, `import a.b.c as x`, or the string form the
      vendored lazy-import tables use;
    - relative to its package: `from .c import x` / `from . import c` inside `a/b/__init__.py`;
    - dynamically: `importlib.import_module(f"a.b.{name}")` — every module under that prefix is
      reachable, so none of them is dead.
    """
    package, _, leaf = module.rpartition(".")
    pattern = re.compile(
        rf"(^|\s)(from|import)\s+{re.escape(module)}\b"
        rf"|[\"']{re.escape(module)}[\"']"
        rf"|[\"']{re.escape(module)}\.\w+[\"']"
    )
    relative = re.compile(
        rf"(^|\s)from\s+\.{{1,2}}\s*{re.escape(leaf)}\b|(^|\s)from\s+\.{re.escape(leaf)}\b"
    )
    hits = []
    for path, text in sources.items():
        if path == self_path:
            continue
        if (
            pattern.search(text)
            or path.parent == self_path.parent
            and relative.search(text)
        ):
            hits.append(path)
    return hits


def dynamic_prefixes(sources: dict[Path, str]) -> set[str]:
    """Prefixes that some file imports through a computed name, e.g.
    `importlib.import_module(f"finscrape.scrapers.{mod}")`."""
    found = set()
    for text in sources.values():
        for match in re.finditer(r"import_module\(f?[\"']([\w.]+)\.\{", text):
            found.add(match.group(1))
    return found


def dead_files() -> list[dict[str, object]]:
    sources = {
        path: path.read_text(encoding="utf-8", errors="replace")
        for path in tracked_python_files()
    }
    report = []
    prefixes = dynamic_prefixes(sources)
    for path in sorted(SCAN.rglob("*.py")):
        if "__pycache__" in path.parts or path.name in ALWAYS_LIVE:
            continue
        module = module_name(path)
        if any(module.startswith(f"{prefix}.") for prefix in prefixes):
            continue
        used_by = importers(module, sources, path)
        if not used_by:
            report.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "module": module,
                    "lines": len(sources[path].splitlines()),
                }
            )
    return report


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    report = dead_files()
    if "--json" in args:
        print(json.dumps(report, indent=2))
        return 0
    total_lines = sum(int(row["lines"]) for row in report)
    print(f"{len(report)} files, {total_lines} lines with no importer", file=sys.stderr)
    for row in report:
        print(f"{row['lines']:>6}  {row['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
