"""`docs/STACK.md` is a set of claims about pins; this reads both sides (plan M3.1).

A stack document drifts the moment someone bumps a pin and forgets the table, and a
wrong floor is worse than no floor: it tells a reader their 3.13 install is supported.
Every assertion below names the file that is authoritative, so the fix is always "update
the doc or the pin", never "loosen the test".
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STACK = (ROOT / "docs" / "STACK.md").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
WEB_PKG = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))


def row(layer: str) -> str:
    """The table row whose first cell is `layer`."""
    for line in STACK.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].startswith(layer):
            return " | ".join(cells)
    raise AssertionError(f"docs/STACK.md has no row for {layer!r}")


def test_the_python_floor_is_the_one_pyproject_declares() -> None:
    requires = PYPROJECT["project"]["requires-python"]  # ">=3.14"
    floor = requires.lstrip(">=")
    assert floor in row("Python")
    # The same floor is what CI installs from; a pin below it would never be tested.
    setup = (ROOT / ".github" / "actions" / "setup-python" / "action.yml").read_text(
        encoding="utf-8"
    )
    assert "3.14" in setup


def test_postgres_is_18_in_the_doc_compose_and_ci() -> None:
    assert "**18**" in row("Postgres")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r"image:\s*postgres:18", compose), "compose must run Postgres 18"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "image: postgres:18" in ci
    assert "POSTGRES_DB: worldfin_test" in ci


def test_the_web_toolchain_versions_are_the_ones_package_json_pins() -> None:
    assert WEB_PKG["devDependencies"]["vite-plus"] in row("Vite+")
    typescript = WEB_PKG["devDependencies"]["typescript"].lstrip("^")
    assert typescript in row("TypeScript")
    # `vite` is an npm alias to the Vite+ core, not upstream Vite: the doc must say so,
    # because `npm i vite@latest` would silently replace the toolchain.
    assert "@voidzero-dev/vite-plus-core" in WEB_PKG["devDependencies"]["vite"]
    assert "vite-plus-core" in row("Vite+")


def test_the_node_floor_is_the_floor_vite_plus_itself_requires() -> None:
    lock = (ROOT / "web" / "package-lock.json").read_text(encoding="utf-8")
    engines = [m for m in re.findall(r'"node":\s*"([^"]+)"', lock)]
    assert any("22.18" in e for e in engines), "the toolchain's own Node floor changed"
    assert "22.18" in row("Node")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "node-version: '26'" in ci
    dockerfile = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
    assert "node:26-slim" in dockerfile


def test_the_parser_on_the_extraction_path_is_on_a_stable_range() -> None:
    deps = PYPROJECT["project"]["dependencies"]
    lxml = next(d for d in deps if d.startswith("lxml"))
    assert lxml == "lxml>=6.0.2,<7", lxml
    assert "6.0.2" in row("lxml")


def test_every_row_names_a_file_that_exists() -> None:
    """The last column is the evidence; a row pointing at a deleted file is a dead claim."""
    for line in STACK.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("Layer", "") or set(cells[0]) <= {"-"}:
            continue
        for token in re.findall(r"`([^`]+)`", cells[-1]):
            if "/" not in token and not token.endswith((".yml", ".md")):
                continue
            assert (ROOT / token).exists(), f"{cells[0]} points at missing {token}"


def test_the_free_threaded_build_is_not_advertised_as_supported() -> None:
    # It exists as a manual side job only; the doc must not read as "we run 3.14t".
    assert "Not adopted" in row("Free-threaded Python")
    assert (ROOT / ".github" / "workflows" / "free-threaded.yml").exists()
