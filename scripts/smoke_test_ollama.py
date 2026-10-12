#!/usr/bin/env python3
"""
PR 1 smoke test — run this after applying pr1_ai_client.py to verify
that Ollama + Qwen 2.5 are working end-to-end.

Usage:
    cd <repo root>
    python scripts/smoke_test_ollama.py

Requires:
    - Ollama running: ollama serve
    - Qwen pulled:   ollama pull qwen2.5:7b  (or :3b)
    - .env set:      OPENAI_BASE_URL=http://localhost:11434/v1
                     OPENAI_API_KEY=ollama
                     FINSCRAPE_MODEL=qwen2.5:7b
"""

import os, sys, json, time

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
failures = []

def check(name, condition, detail=""):
    if condition:
        print(f"  {PASS}  {name}")
    else:
        print(f"  {FAIL}  {name}" + (f": {detail}" if detail else ""))
        failures.append(name)

print("\n=== Smoke test: Ollama + ai_client.py ===\n")

# ── Step 1: environment ────────────────────────────────────────────────────
print("1. Environment")
base_url = os.getenv("OPENAI_BASE_URL", "")
model    = os.getenv("FINSCRAPE_MODEL", "")
check("OPENAI_BASE_URL set",       bool(base_url), base_url or "not set")
check("OPENAI_BASE_URL is Ollama", "11434" in base_url, base_url)
check("FINSCRAPE_MODEL set",       bool(model), model or "not set")

# ── Step 2: Ollama reachable ───────────────────────────────────────────────
print("\n2. Ollama connectivity")
from curl_cffi import requests
try:
    r = requests.get(base_url.replace("/v1", "") + "/api/tags", timeout=5)
    check("Ollama /api/tags responds", r.status_code == 200, f"HTTP {r.status_code}")
    tags = r.json().get("models", [])
    model_names = [m.get("name", "") for m in tags]
    check("Qwen model present", any("qwen" in n.lower() for n in model_names),
          f"Available: {model_names}")
except Exception as e:
    check("Ollama reachable", False, str(e))
    print(f"\n  Make sure Ollama is running: ollama serve")
    sys.exit(1)

# ── Step 3: call_ai returns valid structure ────────────────────────────────
print("\n3. call_ai basic response")
from finscrape.analysis.ai_client import call_ai
from finscrape.analysis.prompts   import SYSTEM_PROMPT

test_text = "Apple Inc. reported record Q1 2025 earnings, beating analyst estimates by 12%. EPS came in at $2.40 vs expected $2.14. Revenue rose 8% to $124.3 billion."

t0 = time.time()
result = call_ai(test_text, SYSTEM_PROMPT)
elapsed = time.time() - t0

check("call_ai returns a dict",          isinstance(result, dict), str(type(result)))
check("result has 'relevant' key",       "relevant" in (result or {}))
check("result has 'signal_score' key",   "signal_score" in (result or {}))
check("signal_score is int",             isinstance((result or {}).get("signal_score"), int),
      str(type((result or {}).get("signal_score"))))
check("signal_score in [-5, 5]",         -5 <= (result or {}).get("signal_score", 999) <= 5)
check("impact_direction valid",
      (result or {}).get("impact_direction") in {"positive","negative","neutral","mixed"},
      str((result or {}).get("impact_direction")))
check("confidence in [0,1]",             0.0 <= (result or {}).get("confidence", -1) <= 1.0)
check("no <think> leak in reasoning",
      "<think>" not in str((result or {}).get("reasoning", "")))
print(f"  Time: {elapsed:.1f}s")

# ── Step 4: cache hit works ────────────────────────────────────────────────
print("\n4. Cache")
t1 = time.time()
result2 = call_ai(test_text, SYSTEM_PROMPT)
cache_elapsed = time.time() - t1
check("Second call returns same result",  result == result2)
check("Cache hit is fast (< 0.1s)",       cache_elapsed < 0.1, f"{cache_elapsed:.3f}s")

from finscrape.analysis.ai_client import get_cache_stats
stats = get_cache_stats()
check("Cache reports 1 hit",              stats["hits"] >= 1, str(stats))

# ── Step 5: known bearish article ─────────────────────────────────────────
print("\n5. Bearish article direction")
bearish_text = "XYZ Corp filed for Chapter 11 bankruptcy protection after failing to service $4.2 billion in debt. Shares plunged 78% in pre-market trading."
bearish = call_ai(bearish_text, SYSTEM_PROMPT)
check("Bearish article gets negative signal",
      (bearish or {}).get("signal_score", 0) < 0,
      f"score={( bearish or {}).get('signal_score')}")
check("Bearish impact_direction is negative",
      (bearish or {}).get("impact_direction") in {"negative"},
      str((bearish or {}).get("impact_direction")))

# ── Summary ────────────────────────────────────────────────────────────────
print(f"\n{'='*45}")
if failures:
    print(f"  {len(failures)} check(s) FAILED: {', '.join(failures)}")
    print(f"  See troubleshooting in README.md")
    sys.exit(1)
else:
    print(f"  All checks passed. PR 1 is working correctly.")
    print(f"\n  Full result from call_ai:")
    print("  " + json.dumps(result, indent=2).replace("\n", "\n  "))
print(f"{'='*45}\n")
