"""Local text embeddings via Ollama — semantic understanding without leaving localhost.

Gives the NLP layer what the lexicon/regex layer can't: paraphrase detection for
dedup (same story from two sources, worded differently) and a base for alias
resolution and event clustering later.

Design constraints:
- Zero new pip dependencies (plain urllib against the local Ollama HTTP API).
- Fully graceful degradation: when Ollama is unreachable, every helper returns
  "not similar"/None and callers behave exactly as they did before. A short
  failure cooldown stops the pipeline from paying a connection timeout per call.
- Cached embeddings (LRU) — articles re-analyzed on retry don't re-embed.

Config: OLLAMA_HOST (default http://localhost:11434),
FINSCRAPE_EMBED_MODEL (default nomic-embed-text).
"""

from __future__ import annotations

import functools
import json
import math
import time
import urllib.error
import urllib.request

from finscrape.settings import env

_HOST = (env("OLLAMA_HOST", "http://localhost:11434") or "").rstrip("/")
_MODEL = env("FINSCRAPE_EMBED_MODEL", "nomic-embed-text") or ""
_TIMEOUT = 8.0
_COOLDOWN = 60.0  # seconds of no-embeddings after a failed call

_failure_ts: list[float] = []  # mutable module state; empty = healthy


def _unavailable() -> bool:
    """True while we're in the post-failure cooldown window."""
    return bool(_failure_ts) and (time.monotonic() - _failure_ts[0]) < _COOLDOWN


@functools.lru_cache(maxsize=1024)
def embed(text: str) -> tuple[float, ...] | None:
    """Embedding vector for `text`, or None when Ollama is unavailable.

    Only the first 400 chars are embedded — headlines and ledes carry the
    identity of a story; long bodies just dilute the vector and slow requests.
    """
    if not text or _unavailable():
        return None
    payload = json.dumps({"model": _MODEL, "prompt": text[:400]}).encode()
    req = urllib.request.Request(
        f"{_HOST}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
        vector = data.get("embedding")
        return tuple(float(x) for x in vector) if vector else None
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        _failure_ts[:] = [time.monotonic()]
        return None


def cosine(a: tuple[float, ...] | None, b: tuple[float, ...] | None) -> float | None:
    """Cosine similarity of two embeddings; None if either side is missing."""
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return None
    return dot / (norm_a * norm_b)


def most_similar(
    text: str,
    candidates: list[tuple[str, str]],
    threshold: float = 0.9,
) -> tuple[str, float] | None:
    """Best-matching candidate above `threshold`.

    Args:
        text: the incoming text.
        candidates: list of (key, text) to compare against.
    Returns:
        (key, similarity) of the best candidate, or None.
    """
    target = embed(text)
    if target is None:
        return None
    best: tuple[str, float] | None = None
    for key, candidate_text in candidates:
        score = cosine(target, embed(candidate_text))
        if score is not None and (best is None or score > best[1]):
            best = (key, score)
    if best and best[1] >= threshold:
        return best
    return None
