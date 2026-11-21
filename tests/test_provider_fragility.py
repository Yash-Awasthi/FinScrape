"""Provider fragility: what happens when the free models refuse (plan m1.3.3).

The replies here are recorded from TokenHarbor and the Render-hosted proxy (notes.md,
23 Nov 2026) rather than invented, so a test failing means the real refusal shapes stopped
being handled. Each test drives the production call path — `_call_openai_proxy`,
`_call_openrouter`, `_dispatch` — and only replaces the HTTP seam.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from finscrape.analysis import ai_client

RECORDED = json.loads(
    (Path(__file__).parent / "fixtures" / "llm_responses.json").read_text(encoding="utf-8")
)


class _Reply:
    """A recorded response, with the fields ai_client touches."""

    def __init__(self, recorded: dict):
        self.status_code = recorded["status"]
        self._body = recorded["body"]
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def _recorded(name: str) -> _Reply:
    return _Reply({k: v for k, v in RECORDED[name].items() if k != "_doc"})


@pytest.fixture(autouse=True)
def _clean_queue(monkeypatch):
    monkeypatch.setattr(ai_client, "_moved_at", {})
    monkeypatch.setattr(ai_client, "RETRY_BASE_DELAY", 0)
    monkeypatch.setenv("FINSCRAPE_WIRE_API", "chat")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.delenv("FINSCRAPE_KEY_RESET_HOURS", raising=False)
    ai_client.clear_cache()
    yield
    ai_client.clear_cache()


def test_a_429_moves_the_key_to_the_back_and_the_next_key_answers(monkeypatch):
    keys = ["key-spent", "key-fresh"]

    def post(url, headers, json, timeout):
        if "spent" in headers["Authorization"]:
            return _recorded("tokenharbor_429_request_forbidden")
        return _recorded("chat_ok")

    monkeypatch.setattr(ai_client.requests, "post", post)
    monkeypatch.setenv("OPENAI_API_KEY", keys[0])
    monkeypatch.setenv("OPENAI_API_KEYS", keys[1])

    assert ai_client._call_openai_proxy("p", "s")["tickers"] == ["XOM"]

    spent = ai_client.key_fingerprint(keys[0])
    assert spent in ai_client.key_moves(), "the 429 is remembered, not swallowed"
    assert ai_client._proxy_keys() == [keys[1], keys[0]], "the spent key is now last"


def test_a_recorded_free_models_disabled_403_reaches_openrouter(monkeypatch):
    """23 Nov: every ingest model answered 403 free_models_disabled. OpenRouter is a
    different account, so the prompt must be retried there before the heuristic writes."""
    asked: list[str] = []

    def post(url, headers, json, timeout):
        asked.append(url)
        if "openrouter" in url:
            return _recorded("chat_ok")
        return _recorded("tokenharbor_403_free_models_disabled")

    monkeypatch.setattr(ai_client.requests, "post", post)
    monkeypatch.setenv("OPENAI_API_KEY", "proxy")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(ai_client, "OPENROUTER_API_KEY", "or-key")

    result = ai_client.call_ai("prompt", "system")

    assert result is not None and result["tickers"] == ["XOM"]
    assert any("openrouter" in url for url in asked), "OpenRouter was never tried"
    assert ai_client.key_moves() == {}, "a 403 is not a spent allowance"


def test_a_recorded_render_request_forbidden_403_is_not_a_429(monkeypatch):
    """TokenHarbor blocks Render's egress with 403 request_forbidden. Rotating keys on it
    would burn the whole queue on a block no key can fix."""
    def post(url, headers, json, timeout):
        return _recorded("render_403_request_forbidden")

    monkeypatch.setattr(ai_client.requests, "post", post)
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEYS", "b")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(ai_client, "OPENROUTER_API_KEY", "")

    assert ai_client._call_openai_proxy("p", "s") is None
    assert ai_client.key_moves() == {}


def test_an_expired_429_gives_the_key_its_place_back(monkeypatch):
    """The free allowance resets, so a 429 old enough to have lapsed must not keep a key at
    the back forever (that is how a queue starves)."""
    now = time.time()
    spent, spent_long_ago, other = "key-a", "key-b", "key-c"
    monkeypatch.setenv("OPENAI_API_KEY", spent)
    monkeypatch.setenv("OPENAI_API_KEYS", f"{spent_long_ago},{other}")
    monkeypatch.setattr(
        ai_client,
        "_moved_at",
        {
            ai_client.key_fingerprint(spent): now - 60,  # 1 minute ago: still spent
            ai_client.key_fingerprint(spent_long_ago): now - 25 * 3600,  # allowance reset
        },
    )

    assert ai_client._proxy_keys() == [spent_long_ago, other, spent]

    # Widen the window past 25 h and the same key is spent again — it is then ordered by
    # its 429 age, so the oldest 429 still leads.
    monkeypatch.setenv("FINSCRAPE_KEY_RESET_HOURS", "48")
    assert ai_client._proxy_keys() == [other, spent_long_ago, spent]
