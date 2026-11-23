"""Prompt versioning + A/B (Phase 13).

A tiny registry of prompt variants so we can run two prompt formulations side by side and
compare their realized accuracy (`/api/accuracy/by-variant`). Assignment is deterministic
per article (hash of the title), so the same story always gets the same variant — no rebias
across re-runs. The chosen variant is stamped into the event's `key_metrics["prompt_variant"]`,
so no schema change is needed.

A/B is **opt-in** (`WORLDFIN_PROMPT_AB=true`); off → always v1 (== the current prompts), so
default behavior and existing tests are unchanged. The AI response cache keys on the full
prompt text, so v1/v2 responses never collide.
"""

from __future__ import annotations

import hashlib

from finscrape.analysis.prompts import ANALYSIS_PROMPT, SYSTEM_PROMPT
from finscrape.settings import env_bool

# v2 — a more conservative calibration variant. Same schema + few-shot, one extra rule.
_V2_SYSTEM = SYSTEM_PROMPT + (
    "\nVARIANT NOTE (v2): be conservative — reserve |signal_score| >= 4 for events with a "
    "clear, quantified market impact, and never exceed 0.8 confidence without a primary source.\n"
)

PROMPT_VARIANTS: dict[str, tuple[str, str]] = {
    "v1": (SYSTEM_PROMPT, ANALYSIS_PROMPT),
    "v2": (_V2_SYSTEM, ANALYSIS_PROMPT),
}
VARIANT_IDS: tuple[str, ...] = tuple(PROMPT_VARIANTS)


def ab_enabled() -> bool:
    return env_bool("WORLDFIN_PROMPT_AB")


def pick_variant(seed: str) -> str:
    """Deterministic variant for an article (hash of `seed`). v1 always when A/B is off."""
    if not ab_enabled():
        return "v1"
    h = int(hashlib.md5((seed or "").encode()).hexdigest(), 16)
    return VARIANT_IDS[h % len(VARIANT_IDS)]


def get_prompts(variant: str) -> tuple[str, str]:
    """(system_prompt, analysis_prompt) for a variant; falls back to v1."""
    return PROMPT_VARIANTS.get(variant, PROMPT_VARIANTS["v1"])
