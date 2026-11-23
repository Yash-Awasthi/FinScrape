"""The one place the ingest half reads the environment (plan M3.4).

Before this module, ~50 call sites across `finscrape/` did their own `os.getenv`, each
with its own idea of what a blank value means and no validation: `int(os.getenv(...))`
raised a bare `ValueError` on a typo, and every module invented its own truthy set. This
is the seam where those rules live, so they are testable and greppable:

    env(name, default)        exact `os.getenv` semantics (None means "unset")
    env_int/env_float         parse, warn and fall back instead of crashing the worker
    env_bool                  the repo's truthy/falsy words, unset -> default
    env_disabled              a switch that defaults to *on* ("0/false/no/off" turns it off)
    env_csv                   comma-separated list, trimmed, empties dropped
    environ()                 the mapping itself, for callers that inject a fake one

Values are read on every call, never cached at import: key rotation and tests that
`monkeypatch.setenv` depend on a live read, and `tests/test_settings_only.py` asserts no
module outside this one (and `server/settings.py`) touches `os.getenv`/`os.environ`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

log = logging.getLogger("finscrape.settings")

TRUTHY = frozenset({"1", "true", "yes", "on"})
FALSY = frozenset({"0", "false", "no", "off"})


def environ() -> Mapping[str, str]:
    return os.environ


def env(name: str, default: str | None = None) -> str | None:
    """Exact `os.getenv`: an unset name returns `default`, a name set to "" returns ""."""
    return os.environ.get(name, default)


def _warn(name: str, raw: str, default: object, kind: str) -> None:
    log.warning("settings: %s=%r is not a valid %s; using %r", name, raw, kind, default)


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        _warn(name, raw, default, "integer")
        return default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        _warn(name, raw, default, "number")
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in TRUTHY:
        return True
    if value in FALSY:
        return False
    _warn(name, raw, default, "boolean")
    return default


def env_disabled(name: str) -> bool:
    """True when the variable is set to one of the off words; unset/garbage stays on."""
    raw = os.environ.get(name)
    return raw is not None and raw.strip().lower() in FALSY


def env_csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.environ.get(name, default)
    return tuple(part.strip() for part in raw.split(",") if part.strip())
