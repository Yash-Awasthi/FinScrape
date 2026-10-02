"""On-demand AI event expansion (GET /api/ai/analyze).

finscrape's `call_ai` validates against the *extraction* schema, so it can't return
this {summary, ticker_impacts, verdict_reason} shape — we make a small free-form chat
call to the same backend (Ollama proxy or OpenRouter BYOK, same env as finscrape).
Degrades gracefully to a deterministic fallback when no LLM is configured or the call
fails, so the endpoint never 500s. Synchronous (requests) — call via asyncio.to_thread.
"""

from __future__ import annotations

import json
import logging
import re

import requests

from server.obs import time_llm
from server.settings import get_settings

log = logging.getLogger("worldfin.ai")

_SYSTEM = "You are a senior financial analyst. Return ONLY valid JSON, no markdown."

_TIMEOUT = 60


def _prompt(event: dict) -> str:
    score = event.get("signal_score", 0)
    sign = "+" if score >= 0 else ""
    tickers = ", ".join(event.get("tickers") or []) or "none identified"
    return (
        "Analyze this news event and return ONLY valid JSON:\n"
        "{\n"
        '  "summary": "2-3 sentence summary of what happened and its market significance",\n'
        '  "ticker_impacts": [\n'
        '    {"ticker": "SYM", "direction": "up|down|neutral", "estimated_pct": "+X-Y%", "reason": "brief reason"}\n'
        "  ],\n"
        f'  "verdict_reason": "One sentence on why this warrants a {event.get("verdict")} verdict"\n'
        "}\n\n"
        f"Subject: {event.get('subject')}\n"
        f"Verdict: {event.get('verdict')} (Score: {sign}{score})\n"
        f"Tickers: {tickers}\n"
        f"Event Type: {event.get('event_type')}\n"
        f"Direction: {event.get('impact_direction')}\n"
        f"Sources: {', '.join(event.get('sources') or [])}"
    )


def _fallback(event: dict) -> dict:
    direction = event.get("impact_direction")
    mapped = (
        "up"
        if direction == "positive"
        else "down"
        if direction == "negative"
        else "neutral"
    )
    return {
        "summary": f"{event.get('subject')} — {event.get('verdict')} signal "
        f"(score {event.get('signal_score')}).",
        "ticker_impacts": [
            {
                "ticker": t,
                "direction": mapped,
                "estimated_pct": "N/A",
                "reason": "heuristic",
            }
            for t in (event.get("tickers") or [])
        ],
        "verdict_reason": f"{event.get('verdict')} based on a {event.get('event_type')} "
        f"event scored {event.get('signal_score')}.",
    }


def _extract_json(text: str) -> dict | None:
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _chat(prompt: str) -> str | None:
    """One OpenAI-compatible chat call to whichever backend is configured."""
    s = get_settings()
    if s.openai_base_url:
        # "ollama" only as the last resort: a local Ollama ignores the bearer entirely,
        # but sending that literal to an endpoint that checks it is a silent 401 and a
        # heuristic answer the caller cannot tell from a real one.
        base = s.openai_base_url.rstrip("/")
        key = s.openai_api_key or "ollama"
        backend = "openai-compatible"
    elif s.openrouter_api_key:
        base, key, backend = (
            "https://openrouter.ai/api/v1",
            s.openrouter_api_key,
            "openrouter",
        )
    else:
        return None
    try:
        with time_llm(backend):
            resp = requests.post(
                f"{base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": s.ai_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        # A bare status hides why a provider refused (bad key vs blocked network).
        body = getattr(getattr(exc, "response", None), "text", "") or ""
        log.warning("ai chat failed: %s %s", exc, body[:300])
        return None


def analyze_event(event: dict) -> dict:
    """Return {summary, ticker_impacts, verdict_reason}. Never raises."""
    text = _chat(_prompt(event))
    parsed = _extract_json(text) if text else None
    if not parsed:
        return _fallback(event)
    return {
        "summary": parsed.get("summary", ""),
        "ticker_impacts": parsed["ticker_impacts"]
        if isinstance(parsed.get("ticker_impacts"), list)
        else [],
        "verdict_reason": parsed.get("verdict_reason", ""),
    }
