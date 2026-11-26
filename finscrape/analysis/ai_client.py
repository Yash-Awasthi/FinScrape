"""
AI client for LLM-based financial event extraction.

Supports two backends:
1. OpenRouter (set OPENROUTER_API_KEY in .env)
2. Local OpenAI-compatible proxy (set OPENAI_BASE_URL env var) — Ollama fits here

Features:
- Retry with exponential backoff (1 retry on failure)
- Response validation (required fields, value ranges)
- LRU + TTL response cache to reduce API costs
- Qwen 2.5 compatibility: <think> block stripping, string→int coercion,
  model-aware cache keys, native Ollama format field
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException
from dotenv import load_dotenv

from finscrape.analysis import budget as budget_guard
from finscrape.analysis.constants import (
    VALID_ACTIONABILITIES,
    VALID_EVENT_TYPES,
    VALID_IMPACT_DIRECTIONS,
    VALID_MAGNITUDES,
    VALID_NOVELTIES,
)
from finscrape.analysis.reply_schema import (
    redacted_sample,
    repair_prompt,
    reply_errors,
)
from finscrape.settings import env, env_float, env_int

logger = logging.getLogger(__name__)

# Load .env from project root
load_dotenv()

OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", "")
OPENAI_BASE_URL    = env("OPENAI_BASE_URL", "")
OPENAI_API_KEY     = env("OPENAI_API_KEY", "proxy")
DEFAULT_MODEL      = env("FINSCRAPE_MODEL", "deepseek/deepseek-chat") or "deepseek/deepseek-chat"
# Wire format for the OPENAI_BASE_URL backend: "chat" (chat/completions, default) or
# "responses" (OpenAI Responses API — e.g. freemodel.dev's free GPT-5.x).
LLM_WIRE_API       = (env("FINSCRAPE_WIRE_API", "chat") or "chat").lower()

# Retry configuration
MAX_RETRIES      = 1
RETRY_BASE_DELAY = 2.0  # seconds

# Cache configuration
CACHE_TTL      = env_int("FINSCRAPE_CACHE_TTL", 3600)
CACHE_MAX_SIZE = env_int("FINSCRAPE_CACHE_MAX_SIZE", 500)

# ---------------------------------------------------------------------------
# Response Cache
# ---------------------------------------------------------------------------

# Every reply the model produced, so a repair attempt can quote what it said. Thread-local
# because the pipeline judges articles on a pool.
_last_reply = threading.local()
_budget_blocked = threading.local()


def begin_analysis() -> None:
    """Reset the per-article budget flag before the analyser makes its first call."""
    _budget_blocked.blocked = False


def budget_blocked() -> bool:
    """True when the last analysed article was refused by the daily token ceiling."""
    return bool(getattr(_budget_blocked, "blocked", False))


class _ResponseCache:
    """Thread-safe LRU + TTL cache for AI responses."""

    def __init__(self, max_size: int = CACHE_MAX_SIZE, ttl: int = CACHE_TTL):
        self._cache: dict[str, tuple[float, dict]] = {}
        self._access_order: list[str] = []
        self._lock = threading.Lock()
        self.max_size = max_size
        self.ttl = ttl
        self.hits = 0
        self.misses = 0

    # FIX #4: model name included in cache key so qwen2.5:3b and qwen2.5:7b
    # never share a cached response.
    def _make_key(self, prompt: str, system_prompt: str, model: str = "") -> str:
        content = f"{model}||{system_prompt}||{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def get(self, prompt: str, system_prompt: str, model: str = "") -> dict | None:
        key = self._make_key(prompt, system_prompt, model)
        with self._lock:
            if key in self._cache:
                expires_at, response = self._cache[key]
                if time.time() < expires_at:
                    self.hits += 1
                    if key in self._access_order:
                        self._access_order.remove(key)
                    self._access_order.append(key)
                    return response
                else:
                    del self._cache[key]
                    if key in self._access_order:
                        self._access_order.remove(key)
            self.misses += 1
            return None

    def put(self, prompt: str, system_prompt: str, response: dict, model: str = "") -> None:
        key = self._make_key(prompt, system_prompt, model)
        with self._lock:
            while len(self._cache) >= self.max_size and self._access_order:
                oldest = self._access_order.pop(0)
                self._cache.pop(oldest, None)
            self._cache[key] = (time.time() + self.ttl, response)
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self.hits = 0
            self.misses = 0

    @property
    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "size":     len(self._cache),
            "max_size": self.max_size,
            "ttl":      self.ttl,
            "hits":     self.hits,
            "misses":   self.misses,
            "hit_rate": round(self.hits / total, 2) if total > 0 else 0.0,
        }


# Global cache instance
_cache = _ResponseCache()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def call_ai(prompt: str, system_prompt: str, model: str | None = None) -> dict | None:
    """
    Send a prompt to the LLM and return parsed JSON response.

    Uses local OpenAI proxy (Ollama) if OPENAI_BASE_URL is set,
    falls back to OpenRouter if OPENROUTER_API_KEY is set.

    Retries once on failure with exponential backoff.
    Validates required fields in the response.
    Returns None on any failure (network, parsing, invalid response).
    Results are cached with TTL to reduce API costs.
    """
    # Read env at call time, not import time — main.py --ollama sets
    # OPENAI_BASE_URL after this module is imported, so frozen constants
    # would never see it.
    primary = model or env("FINSCRAPE_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
    result = _call_model(prompt, system_prompt, primary)
    # A pinned model means that model; otherwise a flaky free-tier primary hands
    # over to the next model in FINSCRAPE_MODEL_FALLBACK (comma-separated).
    if result is None and model is None:
        for fallback in filter(None, (env("FINSCRAPE_MODEL_FALLBACK", "") or "").split(",")):
            logger.info("Primary model %s failed; trying %s", primary, fallback.strip())
            result = _call_model(prompt, system_prompt, fallback.strip())
            if result is not None:
                break
    return result


def _call_model(prompt: str, system_prompt: str, effective_model: str) -> dict | None:
    # Check cache first
    cached = _cache.get(prompt, system_prompt, effective_model)
    if cached is not None:
        logger.debug("Cache hit (hits=%d, rate=%.0f%%)", _cache.hits, _cache.stats["hit_rate"] * 100)
        return cached

    reserved = budget_guard.estimate_request_tokens(prompt, system_prompt)
    if not budget_guard.reserve(reserved):
        _budget_blocked.blocked = True
        logger.warning(
            "budget: daily token ceiling reached (used=%d ceiling=%d); "
            "model=%s skipped",
            budget_guard.used(),
            budget_guard.ceiling(),
            effective_model,
        )
        return None

    _last_reply.text = ""
    raw = _dispatch(prompt, system_prompt, effective_model)
    budget_guard.settle(
        reserved,
        budget_guard.estimate_tokens(prompt)
        + budget_guard.estimate_tokens(system_prompt)
        + budget_guard.estimate_tokens(_recall()),
    )
    source = "model"

    # A reply that does not parse leaves no dict to repair, only the text it sent. Both
    # failure shapes get the same treatment: one repair attempt with the problem quoted.
    errors = reply_errors(raw) if raw is not None else []
    if raw is None or errors:
        broken = _recall()
        if not broken:
            return None
        if errors:
            logger.warning(
                "schema_invalid model=%s errors=%s sample=%s",
                effective_model,
                "; ".join(errors),
                redacted_sample(broken),
            )
        else:
            logger.warning(
                "json_invalid model=%s sample=%s", effective_model, redacted_sample(broken)
            )
        repair_text = repair_prompt(prompt, redacted_sample(broken), errors)
        repair_reserved = budget_guard.estimate_request_tokens(
            repair_text, system_prompt
        )
        if not budget_guard.reserve(repair_reserved):
            _budget_blocked.blocked = True
            logger.warning(
                "budget: daily token ceiling reached during repair; model=%s skipped",
                effective_model,
            )
            return None
        repaired = _dispatch(repair_text, system_prompt, effective_model)
        budget_guard.settle(
            repair_reserved,
            budget_guard.estimate_tokens(repair_text)
            + budget_guard.estimate_tokens(system_prompt)
            + budget_guard.estimate_tokens(_recall()),
        )
        if repaired is None:
            logger.error("repair_failed model=%s", effective_model)
            return None
        raw, source = repaired, "model_repaired"
        if reply_errors(raw):
            logger.error(
                "schema_invalid model=%s after repair errors=%s sample=%s",
                effective_model,
                "; ".join(reply_errors(raw)),
                redacted_sample(raw),
            )
            return None

    result = _validate_response(raw)

    if result is not None:
        result["analysis_source"] = source
        result["model_name"] = effective_model
        _cache.put(prompt, system_prompt, result, effective_model)

    return result


def _dispatch(prompt: str, system_prompt: str, effective_model: str) -> dict | None:
    """One attempt at one model, across whichever backends are configured."""
    base_url = env("OPENAI_BASE_URL", "") or ""
    openrouter_key = env("OPENROUTER_API_KEY", "")

    if base_url and (env("FINSCRAPE_WIRE_API", "chat") or "chat").lower() == "responses":
        return _call_with_retry(_call_responses_api, prompt, system_prompt, effective_model)
    if base_url:
        raw = _call_with_retry(_call_openai_proxy, prompt, system_prompt, effective_model)
        # A proxy can be up while its free-model route is disabled (403
        # free_models_disabled). OpenRouter is a different account, so try it
        # before giving up and letting the heuristic fallback write the event.
        if raw is None and openrouter_key:
            logger.info("Primary proxy failed; trying OpenRouter")
            return _call_with_retry(
                _call_openrouter,
                prompt,
                system_prompt,
                env("FINSCRAPE_OPENROUTER_MODEL", DEFAULT_MODEL),
            )
        return raw
    if openrouter_key:
        return _call_with_retry(_call_openrouter, prompt, system_prompt, effective_model)

    logger.error("No AI backend configured. Set OPENROUTER_API_KEY or OPENAI_BASE_URL.")
    return None


def _recall() -> str:
    """The text of this thread's last model reply, empty when the model never answered."""
    return getattr(_last_reply, "text", "")


def get_cache_stats() -> dict:
    return _cache.stats


def clear_cache() -> None:
    _cache.clear()


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

def _call_with_retry(fn, prompt, system_prompt, model):
    for attempt in range(MAX_RETRIES + 1):
        result = fn(prompt, system_prompt, model)
        if result is not None:
            return result
        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.info("Retrying AI call in %.1fs (attempt %d/%d)", delay, attempt + 1, MAX_RETRIES)
            time.sleep(delay)
    return None


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def _validate_response(data: dict) -> dict | None:
    """
    Validate and normalize an AI analysis response.
    Handles Qwen 2.5 quirks: null signal_score, string signal_score.
    """
    if not isinstance(data, dict):
        logger.error("AI response is not a dict: %s", type(data))
        return None

    if "relevant" not in data:
        logger.warning("AI response missing 'relevant' field; defaulting to False")
        data["relevant"] = False

    if not data.get("relevant", False):
        return data

    # Normalize event_type
    et = data.get("event_type", "other")
    if et not in VALID_EVENT_TYPES:
        logger.warning("AI returned unknown event_type %r; coercing to 'other'", et)
        data["event_type"] = "other"

    # Normalize impact_direction
    direction = data.get("impact_direction", "neutral")
    if direction not in VALID_IMPACT_DIRECTIONS:
        data["impact_direction"] = "neutral"

    # FIX #3a: handle null signal_score (Qwen sometimes returns null at temp=0.1)
    if data.get("signal_score") is None:
        data["signal_score"] = 0

    # FIX #3b: coerce string signal_score → int (Qwen quirk: returns "3" not 3)
    score = data.get("signal_score", 0)
    if isinstance(score, str):
        try:
            score = int(score)
        except ValueError:
            score = 0
    if isinstance(score, (int, float)):
        data["signal_score"] = max(-5, min(5, int(score)))
    else:
        data["signal_score"] = 0

    # Clamp confidence to [0.0, 1.0]
    conf = data.get("confidence", 0.5)
    if conf is None:
        conf = 0.5
    if isinstance(conf, str):
        try:
            conf = float(conf)
        except ValueError:
            conf = 0.5
    if isinstance(conf, (int, float)):
        data["confidence"] = max(0.0, min(1.0, float(conf)))
    else:
        data["confidence"] = 0.5

    # Normalize magnitude
    mag = data.get("magnitude", "medium")
    if mag not in VALID_MAGNITUDES:
        data["magnitude"] = "medium"

    # Normalize novelty
    nov = data.get("novelty", "standard")
    if nov not in VALID_NOVELTIES:
        data["novelty"] = "standard"

    # Normalize actionability
    act = data.get("actionability", "medium")
    if act not in VALID_ACTIONABILITIES:
        data["actionability"] = "medium"

    # Ensure lists/dicts exist
    if not isinstance(data.get("tickers"), list):
        data["tickers"] = []
    if not isinstance(data.get("affected_entities"), list):
        data["affected_entities"] = []
    if not isinstance(data.get("second_order_effects"), list):
        data["second_order_effects"] = []
    if not isinstance(data.get("key_metrics"), dict):
        data["key_metrics"] = {}

    data.setdefault("subject", "")
    data.setdefault("reasoning", "")
    data.setdefault("sector_impact", "")
    data.setdefault("temporal_context", "standard")

    return data


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

# Key fingerprint -> time of its last 429. worker.key_queue keeps it in Postgres so the
# queue order survives between ingest runs.
_moved_at: dict[str, float] = {}
_key_lock = threading.Lock()


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def key_moves() -> dict[str, float]:
    with _key_lock:
        return dict(_moved_at)


def load_key_moves(moves: dict[str, float]) -> None:
    with _key_lock:
        _moved_at.update(moves)


def _proxy_keys() -> list[str]:
    """Key queue over OPENAI_API_KEY and the comma-separated OPENAI_API_KEYS: the key
    whose last 429 is oldest leads, ties in that listed order.

    A 429 older than the allowance window no longer means anything — the free quota has
    reset — so that key rejoins the front. Without this a queue where every key spent its
    allowance once stays spent-looking forever, even after the provider reset it.
    """
    keys = [
        env("OPENAI_API_KEY", "proxy") or "proxy",
        *(env("OPENAI_API_KEYS", "") or "").split(","),
    ]
    keys = [k for k in dict.fromkeys(k.strip() for k in keys) if k]
    # TokenHarbor's own reset is not published (docs/COST.md); 24 h is the conservative
    # assumption, and FINSCRAPE_KEY_RESET_HOURS overrides it once the account says more.
    reset_after = env_float("FINSCRAPE_KEY_RESET_HOURS", 24.0) * 3600
    now = time.time()

    def rank(key: str) -> float:
        moved = _moved_at.get(key_fingerprint(key), 0.0)
        return 0.0 if not moved or now - moved >= reset_after else moved

    with _key_lock:
        return sorted(keys, key=rank)


def _call_openai_proxy(prompt: str, system_prompt: str, model: str | None = None) -> dict | None:
    """
    Call local OpenAI-compatible proxy (Ollama or any other).

    FIX #1: Adds Ollama-native `format: "json"` alongside `response_format`
    for more reliable JSON output from Qwen 2.5. Other providers ignore
    the extra field.
    """
    try:
        for key in _proxy_keys():
            response = requests.post(
                f"{env('OPENAI_BASE_URL', '')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":    model or env("FINSCRAPE_MODEL", DEFAULT_MODEL),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature":     env_float("FINSCRAPE_AI_TEMP", 0.1),
                    # Reasoning models (mimo) spend 800 tokens thinking and return no JSON.
                    "max_tokens":      env_int("FINSCRAPE_AI_MAX_TOKENS", 3000),
                    "response_format": {"type": "json_object"},
                    "format":          "json",  # Ollama-native; ignored by other providers
                },
                timeout=env_int("FINSCRAPE_AI_TIMEOUT", 60),
            )
            if response.status_code != 429:
                break
            with _key_lock:
                _moved_at[key_fingerprint(key)] = time.time()
            logger.warning("AI proxy key ...%s answered 429, moved to the back", key[-4:])

        if response.status_code != 200:
            logger.error("AI proxy HTTP %d: %s", response.status_code, response.text[:200])
            return None

        return _parse_response(response.json())

    except Exception as e:
        logger.error("AI proxy error: %s", e)
        return None


def _call_openrouter(prompt: str, system_prompt: str, model: str | None = None) -> dict | None:
    """Call OpenRouter API."""
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":    model or DEFAULT_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                "temperature":     env_float("FINSCRAPE_AI_TEMP", 0.1),
                "max_tokens":      800,
                "response_format": {"type": "json_object"},
            },
            timeout=env_int("FINSCRAPE_AI_TIMEOUT", 45),
        )

        if response.status_code != 200:
            logger.error("AI HTTP %d: %s", response.status_code, response.text[:200])
            return None

        return _parse_response(response.json())

    except RequestException as e:
        logger.error("AI request error: %s", e)
        return None
    except Exception as e:
        logger.error("AI unexpected error: %s", e)
        return None


def _extract_json_from_text(content: str) -> dict | None:
    """Strip <think> reasoning blocks then pull the JSON object out of the text."""
    content = re.sub(r"<think>[\s\S]*?</think>", "", content or "", flags=re.IGNORECASE).strip()
    # Remembered even when the parse fails: a repair attempt quotes this back.
    _last_reply.text = content
    try:
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            return json.loads(match.group(0))
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error("AI JSON parse error: %s | Content: %s", e, content[:200])
        return None


def _responses_text(data: dict) -> str:
    """Pull the assistant text out of an OpenAI Responses-API payload."""
    if data.get("output_text"):
        return data["output_text"]
    parts: list[str] = []
    for item in data.get("output", []):
        for c in item.get("content", []) if isinstance(item, dict) else []:
            if c.get("type") in ("output_text", "text") and c.get("text"):
                parts.append(c["text"])
    return "\n".join(parts)


def _call_responses_api(prompt: str, system_prompt: str, model: str | None = None) -> dict | None:
    """Call an OpenAI Responses-API backend (freemodel.dev) — system→instructions,
    user→input. Reasoning models need output-token headroom."""
    try:
        response = requests.post(
            f"{(OPENAI_BASE_URL or '').rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model or DEFAULT_MODEL,
                "instructions": system_prompt,
                "input": prompt,
                "store": False,
                "max_output_tokens": env_int("FINSCRAPE_AI_MAX_TOKENS", 3000),
                "reasoning": {"effort": env("FINSCRAPE_AI_EFFORT", "low")},
            },
            timeout=env_int("FINSCRAPE_AI_TIMEOUT", 90),
        )
        if response.status_code != 200:
            logger.error("AI responses HTTP %d: %s", response.status_code, response.text[:200])
            return None
        return _extract_json_from_text(_responses_text(response.json()))
    except Exception as e:
        logger.error("AI responses error: %s", e)
        return None


def _parse_response(data: dict) -> dict | None:
    """Extract + parse JSON from a chat/completions response (Qwen <think> aware)."""
    if "choices" not in data:
        logger.error("AI response missing 'choices' key")
        return None
    return _extract_json_from_text(data["choices"][0]["message"]["content"])
