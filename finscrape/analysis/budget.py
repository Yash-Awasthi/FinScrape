"""Daily token ceiling for model calls.

The free models are the cost ceiling a busy day reaches first. This guard counts the
tokens the analyser asks for, and once the day's allowance is spent the model call is
skipped: the pipeline falls back to the deterministic analyst and stamps the row with
`key_metrics["fallback_reason"] = "daily_token_ceiling"`, so a downgraded verdict is
visible rather than silent.

Knobs:

    FINSCRAPE_DAILY_TOKEN_CEILING   tokens per UTC day; 0 (default) disables the guard
    FINSCRAPE_BUDGET_STATE          state file; defaults to a temp file per host
    FINSCRAPE_OUTPUT_TOKEN_RESERVE  tokens held back for the reply (default 300)

The state file is per host, because the API and the worker do not share a filesystem on
the free stack. That is a ceiling per process host, not a global one; a shared ceiling
would need Redis, which the multi-replica design already requires for rate limits.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from finscrape.settings import env, env_int

_LOCK = threading.Lock()


def estimate_tokens(text: str) -> int:
    """Chars/4, the same planning approximation `scripts/cost_model.py` uses."""
    return max(1, math.ceil(len(text) / 4))


def ceiling() -> int:
    return max(0, env_int("FINSCRAPE_DAILY_TOKEN_CEILING", 0))


def output_reserve() -> int:
    return max(0, env_int("FINSCRAPE_OUTPUT_TOKEN_RESERVE", 300))


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _state_path() -> Path:
    configured = env("FINSCRAPE_BUDGET_STATE", "") or ""
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "finscrape-budget.json"


def _read(day: str) -> int:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except OSError, ValueError:
        return 0
    if not isinstance(data, dict) or data.get("date") != day:
        return 0
    try:
        return max(0, int(data.get("tokens", 0)))
    except TypeError, ValueError:
        return 0


def _write(day: str, tokens: int) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps({"date": day, "tokens": int(tokens)}), encoding="utf-8")
    os.replace(tmp, path)


def estimate_request_tokens(prompt: str, system_prompt: str) -> int:
    """Input estimate plus the reply reserve, the amount one attempt may spend."""
    return estimate_tokens(prompt) + estimate_tokens(system_prompt) + output_reserve()


def reserve(tokens: int) -> bool:
    """Atomically hold `tokens` against today's ceiling; False means do not call."""
    limit = ceiling()
    if limit <= 0 or tokens <= 0:
        return True
    day = _today()
    with _LOCK:
        used = _read(day)
        if used + tokens > limit:
            return False
        _write(day, used + tokens)
        return True


def settle(reserved: int, actual: int) -> None:
    """Replace a reservation with what the call actually spent (never below zero)."""
    limit = ceiling()
    if limit <= 0 or reserved <= 0:
        return
    day = _today()
    with _LOCK:
        used = _read(day)
        _write(day, max(0, used - reserved + max(0, actual)))


def used() -> int:
    """Tokens recorded for the current UTC day; 0 when the guard is off."""
    return _read(_today())


def status() -> dict:
    return {"date": _today(), "used": used(), "ceiling": ceiling()}
