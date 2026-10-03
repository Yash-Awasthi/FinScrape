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
import os
import re
import threading
import time

import requests
from dotenv import load_dotenv

from finscrape.analysis.constants import (
    VALID_ACTIONABILITIES,
    VALID_EVENT_TYPES,
    VALID_IMPACT_DIRECTIONS,
    VALID_MAGNITUDES,
    VALID_NOVELTIES,
)

logger = logging.getLogger(__name__)

# Load .env from project root
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_BASE_URL    = os.getenv("OPENAI_BASE_URL", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "proxy")
DEFAULT_MODEL      = os.getenv("FINSCRAPE_MODEL", "deepseek/deepseek-chat")
# Wire format for the OPENAI_BASE_URL backend: "chat" (chat/completions, default) or
# "responses" (OpenAI Responses API — e.g. freemodel.dev's free GPT-5.x).
LLM_WIRE_API       = os.getenv("FINSCRAPE_WIRE_API", "chat").lower()

# Retry configuration
MAX_RETRIES      = 1
RETRY_BASE_DELAY = 2.0  # seconds

# Cache configuration
CACHE_TTL      = int(os.getenv("FINSCRAPE_CACHE_TTL",      "3600"))
CACHE_MAX_SIZE = int(os.getenv("FINSCRAPE_CACHE_MAX_SIZE", "500"))

# ---------------------------------------------------------------------------
# Response Cache
# ---------------------------------------------------------------------------

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
    primary = model or os.getenv("FINSCRAPE_MODEL", DEFAULT_MODEL)
    result = _call_model(prompt, system_prompt, primary)
    # A pinned model means that model; otherwise a flaky free-tier primary hands
    # over to the next model in FINSCRAPE_MODEL_FALLBACK (comma-separated).
    if result is None and model is None:
        for fallback in filter(None, os.getenv("FINSCRAPE_MODEL_FALLBACK", "").split(",")):
            logger.info("Primary model %s failed; trying %s", primary, fallback.strip())
            result = _call_model(prompt, system_prompt, fallback.strip())
            if result is not None:
                break
    return result


def _call_model(prompt: str, system_prompt: str, effective_model: str) -> dict | None:
    base_url = os.getenv("OPENAI_BASE_URL", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

    # Check cache first
    cached = _cache.get(prompt, system_prompt, effective_model)
    if cached is not None:
        logger.debug("Cache hit (hits=%d, rate=%.0f%%)", _cache.hits, _cache.stats["hit_rate"] * 100)
        return cached

    if base_url and os.getenv("FINSCRAPE_WIRE_API", "chat").lower() == "responses":
        raw = _call_with_retry(_call_responses_api, prompt, system_prompt, effective_model)
    elif base_url:
        raw = _call_with_retry(_call_openai_proxy, prompt, system_prompt, effective_model)
    elif openrouter_key:
        raw = _call_with_retry(_call_openrouter, prompt, system_prompt, effective_model)
    else:
        logger.error("No AI backend configured. Set OPENROUTER_API_KEY or OPENAI_BASE_URL.")
        return None

    if raw is None:
        return None

    result = _validate_response(raw)

    if result is not None:
        _cache.put(prompt, system_prompt, result, effective_model)

    return result


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
    whose last 429 is oldest leads, ties in that listed order."""
    keys = [os.getenv("OPENAI_API_KEY", "proxy"), *os.getenv("OPENAI_API_KEYS", "").split(",")]
    keys = [k for k in dict.fromkeys(k.strip() for k in keys) if k]
    with _key_lock:
        return sorted(keys, key=lambda k: _moved_at.get(key_fingerprint(k), 0.0))


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
                f"{os.getenv('OPENAI_BASE_URL', '')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":    model or os.getenv("FINSCRAPE_MODEL", DEFAULT_MODEL),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature":     float(os.getenv("FINSCRAPE_AI_TEMP", "0.1")),
                    # Reasoning models (mimo) spend 800 tokens thinking and return no JSON.
                    "max_tokens":      int(os.getenv("FINSCRAPE_AI_MAX_TOKENS", "3000")),
                    "response_format": {"type": "json_object"},
                    "format":          "json",  # Ollama-native; ignored by other providers
                },
                timeout=int(os.getenv("FINSCRAPE_AI_TIMEOUT", "60")),
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
                "temperature":     float(os.getenv("FINSCRAPE_AI_TEMP", "0.1")),
                "max_tokens":      800,
                "response_format": {"type": "json_object"},
            },
            timeout=int(os.getenv("FINSCRAPE_AI_TIMEOUT", "45")),
        )

        if response.status_code != 200:
            logger.error("AI HTTP %d: %s", response.status_code, response.text[:200])
            return None

        return _parse_response(response.json())

    except requests.exceptions.RequestException as e:
        logger.error("AI request error: %s", e)
        return None
    except Exception as e:
        logger.error("AI unexpected error: %s", e)
        return None


def _extract_json_from_text(content: str) -> dict | None:
    """Strip <think> reasoning blocks then pull the JSON object out of the text."""
    content = re.sub(r"<think>[\s\S]*?</think>", "", content or "", flags=re.IGNORECASE).strip()
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
            f"{OPENAI_BASE_URL.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model or DEFAULT_MODEL,
                "instructions": system_prompt,
                "input": prompt,
                "store": False,
                "max_output_tokens": int(os.getenv("FINSCRAPE_AI_MAX_TOKENS", "3000")),
                "reasoning": {"effort": os.getenv("FINSCRAPE_AI_EFFORT", "low")},
            },
            timeout=int(os.getenv("FINSCRAPE_AI_TIMEOUT", "90")),
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
