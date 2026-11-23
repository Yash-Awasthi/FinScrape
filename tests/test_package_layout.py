"""The package split is real, and the old paths are only shims (plan M3.4).

`finscrape/` grew one module per idea with no grouping. The split gives each layer a
home — `fetchers/` (network), `extract/` (text → symbols), `analysis/` (the model and
its validators), `signals/` (the derived calls) — and keeps the old import paths alive
for anything outside the repository. This test is what makes "with re-export shims"
checkable: a shim that starts containing logic fails here.
"""

from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CANONICAL = {
    "finscrape.fetchers": ROOT / "finscrape" / "fetchers" / "__init__.py",
    "finscrape.fetchers.ingestors": ROOT
    / "finscrape"
    / "fetchers"
    / "ingestors"
    / "__init__.py",
    "finscrape.extract.entity_map": ROOT / "finscrape" / "extract" / "entity_map.py",
    "finscrape.signals.accuracy": ROOT / "finscrape" / "signals" / "accuracy.py",
    "finscrape.signals.prediction": ROOT / "finscrape" / "signals" / "prediction.py",
    "finscrape.signals.scenarios": ROOT / "finscrape" / "signals" / "scenarios.py",
}

SHIMS = {
    "finscrape.scrapers": ROOT / "finscrape" / "scrapers" / "__init__.py",
    "finscrape.ingestors": ROOT / "finscrape" / "ingestors" / "__init__.py",
    "finscrape.entity_map": ROOT / "finscrape" / "entity_map.py",
    "finscrape.accuracy": ROOT / "finscrape" / "accuracy.py",
    "finscrape.prediction": ROOT / "finscrape" / "prediction.py",
    "finscrape.scenarios": ROOT / "finscrape" / "scenarios.py",
}


def test_each_layer_has_its_own_module() -> None:
    for module, path in CANONICAL.items():
        assert path.is_file(), module
        assert importlib.import_module(module) is not None


def test_a_shim_re_exports_and_holds_no_logic() -> None:
    for path in SHIMS.values():
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith(("#", '"""', "from ", ")"))
        ]
        # Only the module docstring, an import (possibly wrapped) and `__all__` are
        # allowed. A def/class/assignment means the shim became a second implementation.
        assert not [line for line in lines if line.startswith(("def ", "class "))], path
        assert not [line for line in lines if "=" in line and "__all__" not in line], (
            path
        )


def test_the_split_moved_the_files_rather_than_copying_them() -> None:
    # The old packages keep nothing but a shim: one `__init__.py`, no source modules.
    for folder in ("scrapers", "ingestors"):
        strays = [
            p.name
            for p in (ROOT / "finscrape" / folder).glob("*.py")
            if p.name != "__init__.py"
        ]
        assert strays == [], f"left behind in finscrape/{folder}: {strays}"
    assert (ROOT / "finscrape" / "fetchers" / "world" / "feeds.py").is_file()


def test_nothing_inside_the_repository_imports_the_shims() -> None:
    """The shims exist for outside callers; our own code must use the canonical path."""
    legacy = tuple(f"{name.split('.')[1]}." for name in SHIMS)
    offenders: list[str] = []
    for folder in ("finscrape", "server", "worker", "scripts", "tests"):
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" in path.parts or path.parent.name in (
                "scrapers",
                "ingestors",
            ):
                continue
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "import" not in line:
                    continue
                for name in legacy:
                    if f"finscrape.{name}" in line:
                        offenders.append(f"{path.relative_to(ROOT)}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)


def test_the_shim_and_the_canonical_module_are_the_same_object() -> None:
    from finscrape import accuracy, entity_map, prediction, scenarios, scrapers
    from finscrape.extract import entity_map as canonical_entity
    from finscrape.fetchers import BaseScraper
    from finscrape.signals import accuracy as canonical_accuracy

    assert scrapers.BaseScraper is BaseScraper
    assert (
        entity_map.resolve_company_tickers is canonical_entity.resolve_company_tickers
    )
    assert accuracy.calibration is canonical_accuracy.calibration
    assert callable(prediction.reliability_tables)
    assert callable(scenarios.event_weight)
