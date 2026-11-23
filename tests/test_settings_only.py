"""Environment reads live in one module, and parsing is forgiving (plan M3.4).

The grep half is the real gate: before this, ~50 call sites each did `int(os.getenv(...))`,
so a typo crashed the worker with a bare ValueError and every module had its own idea of
which strings meant "on". The behaviour half pins that the shared readers keep the old
defaults when a value is missing or nonsense.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from finscrape import settings

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("finscrape", "server", "worker")
EXEMPT = {"finscrape/settings.py", "server/settings.py"}
PATTERN = re.compile(r"\bos\.(getenv|environ)\b")


def _offenders() -> list[str]:
    found: list[str] = []
    for folder in SCANNED:
        for path in sorted((ROOT / folder).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel in EXEMPT or "__pycache__" in rel:
                continue
            for line_no, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if PATTERN.search(line):
                    found.append(f"{rel}:{line_no}: {line.strip()}")
    return found


def test_no_module_reads_the_environment_directly() -> None:
    offenders = _offenders()
    assert offenders == [], "read these through finscrape/settings.py:\n" + "\n".join(
        offenders
    )


def test_the_grep_would_catch_a_new_read() -> None:
    # A gate that cannot fail is not a gate: prove the pattern matches a real line.
    assert PATTERN.search('x = os.getenv("FINSCRAPE_MODEL")')
    assert PATTERN.search("x = os.environ")


def test_unset_returns_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORLDFIN_TEST_UNSET", raising=False)
    assert settings.env("WORLDFIN_TEST_UNSET") is None
    assert settings.env("WORLDFIN_TEST_UNSET", "fallback") == "fallback"
    assert settings.env_int("WORLDFIN_TEST_UNSET", 7) == 7
    assert settings.env_float("WORLDFIN_TEST_UNSET", 1.5) == 1.5


def test_an_explicit_empty_string_is_not_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `os.getenv` semantics: "" is a value. The old `or default` idiom silently
    # replaced it, which is how an empty OPENAI_API_KEY became "proxy".
    monkeypatch.setenv("WORLDFIN_TEST_EMPTY", "")
    assert settings.env("WORLDFIN_TEST_EMPTY", "fallback") == ""
    assert settings.env_int("WORLDFIN_TEST_EMPTY", 5) == 5


def test_nonsense_numbers_warn_and_fall_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("WORLDFIN_TEST_BAD", "sixty")
    with caplog.at_level("WARNING", logger="finscrape.settings"):
        assert settings.env_int("WORLDFIN_TEST_BAD", 60) == 60
        assert settings.env_float("WORLDFIN_TEST_BAD", 0.5) == 0.5
    # A bad value is reported once per read rather than crashing the worker at import.
    assert "WORLDFIN_TEST_BAD='sixty' is not a valid integer" in caplog.text
    assert "WORLDFIN_TEST_BAD='sixty' is not a valid number" in caplog.text


def test_booleans_accept_the_words_the_repo_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for word in ("1", "true", "YES", "on"):
        monkeypatch.setenv("WORLDFIN_TEST_FLAG", word)
        assert settings.env_bool("WORLDFIN_TEST_FLAG") is True
    for word in ("0", "false", "No", "OFF"):
        monkeypatch.setenv("WORLDFIN_TEST_FLAG", word)
        assert settings.env_bool("WORLDFIN_TEST_FLAG") is False
    monkeypatch.setenv("WORLDFIN_TEST_FLAG", "perhaps")
    assert settings.env_bool("WORLDFIN_TEST_FLAG", True) is True


def test_disabled_switch_defaults_to_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORLDFIN_TEST_SWITCH", raising=False)
    assert settings.env_disabled("WORLDFIN_TEST_SWITCH") is False
    monkeypatch.setenv("WORLDFIN_TEST_SWITCH", "nonsense")
    assert settings.env_disabled("WORLDFIN_TEST_SWITCH") is False
    monkeypatch.setenv("WORLDFIN_TEST_SWITCH", "off")
    assert settings.env_disabled("WORLDFIN_TEST_SWITCH") is True


def test_csv_drops_blank_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORLDFIN_TEST_LIST", " a, ,b ,")
    assert settings.env_csv("WORLDFIN_TEST_LIST") == ("a", "b")


def test_the_pipeline_does_not_print() -> None:
    # The ingest half logs; only the CLI shims print, because their stdout *is* the
    # output. A stray print inside the pipeline bypasses the JSON handler and the
    # correlation id, which is exactly what the structured logger exists to carry.
    source = (ROOT / "finscrape" / "pipeline.py").read_text(encoding="utf-8")
    assert "print(" not in source
    assert "stage=" in source
