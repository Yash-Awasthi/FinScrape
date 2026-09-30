"""Point production at an LLM: one command updates GitHub Actions and the Render API.

    python scripts/llm.py --model deepseek-v4.1-flash:free --url https://tokenharbor.ai/v1 \
        [--key sk-...] [--fallback mimo-v2.6-flash:free]

Any flag left out keeps its current value. The key goes to the GitHub secret and to
Render; the rest are GitHub variables. Render needs RENDER_API_KEY (env or .env).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = "https://api.render.com/v1"
SERVICE = "winfin-api"


def settings(args: argparse.Namespace) -> dict[str, str]:
    """Env name -> value for every flag given."""
    pairs = {
        "FINSCRAPE_MODEL": args.model,
        "OPENAI_BASE_URL": args.url,
        "OPENAI_API_KEY": args.key,
        "FINSCRAPE_MODEL_FALLBACK": args.fallback,
    }
    return {k: v for k, v in pairs.items() if v is not None}


def github(values: dict[str, str]) -> None:
    for name, value in values.items():
        kind = "secret" if name == "OPENAI_API_KEY" else "variable"
        subprocess.run(["gh", kind, "set", name, "--body", value], check=True, cwd=ROOT)
        print(f"github {kind} {name} set")


def _render(method: str, path: str, token: str, body: object = None) -> object:
    req = urllib.request.Request(
        RENDER + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def render(values: dict[str, str], token: str) -> None:
    services = _render("GET", f"/services?name={SERVICE}&limit=1", token)
    service_id = services[0]["service"]["id"]  # type: ignore[index]
    for name, value in values.items():
        _render("PUT", f"/services/{service_id}/env-vars/{name}", token, {"value": value})
        print(f"render {name} set")
    _render("POST", f"/services/{service_id}/deploys", token, {})
    print("render redeploy started")


def render_token() -> str:
    token = os.environ.get("RENDER_API_KEY", "")
    env = ROOT / ".env"
    if not token and env.exists():
        for line in env.read_text("utf-8").splitlines():
            if line.startswith("RENDER_API_KEY="):
                token = line.split("=", 1)[1].strip()
    return token


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model")
    ap.add_argument("--url")
    ap.add_argument("--key")
    ap.add_argument("--fallback")
    values = settings(ap.parse_args())
    if not values:
        ap.error("give at least one of --model, --url, --key, --fallback")
    github(values)
    if token := render_token():
        render(values, token)
    else:
        print("RENDER_API_KEY not set: set these in the Render dashboard for winfin-api:")
        for name, value in values.items():
            print(f"  {name}={value}")


if __name__ == "__main__":
    main()
