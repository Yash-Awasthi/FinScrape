"""call_ai falls back to FINSCRAPE_MODEL_FALLBACK when the primary model fails."""

from finscrape.analysis import ai_client

GOOD = {
    "relevant": True,
    "event_type": "other",
    "subject": "x",
    "tickers": ["XOM"],
    "impact_direction": "neutral",
    "signal_score": 0,
    "confidence": 0.5,
}


def test_primary_failure_uses_the_fallback_model(monkeypatch):
    asked: list[str] = []

    def proxy(prompt, system_prompt, model):
        asked.append(model)
        return dict(GOOD) if model == "backup" else None

    ai_client.clear_cache()
    monkeypatch.setattr(ai_client, "_call_openai_proxy", proxy)
    monkeypatch.setattr(ai_client, "RETRY_BASE_DELAY", 0)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("FINSCRAPE_WIRE_API", "chat")
    monkeypatch.setenv("FINSCRAPE_MODEL", "primary")
    monkeypatch.setenv("FINSCRAPE_MODEL_FALLBACK", "backup")
    result = ai_client.call_ai("prompt", "system")
    assert result is not None and result["tickers"] == ["XOM"]
    assert asked[-1] == "backup" and asked[0] == "primary"


def test_an_explicit_model_never_falls_back(monkeypatch):
    asked: list[str] = []

    def proxy(prompt, system_prompt, model):
        asked.append(model)

    ai_client.clear_cache()
    monkeypatch.setattr(ai_client, "_call_openai_proxy", proxy)
    monkeypatch.setattr(ai_client, "RETRY_BASE_DELAY", 0)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("FINSCRAPE_WIRE_API", "chat")
    monkeypatch.setenv("FINSCRAPE_MODEL_FALLBACK", "backup")
    assert ai_client.call_ai("prompt", "system", model="pinned") is None
    assert set(asked) == {"pinned"}


def test_chat_call_leaves_reasoning_models_room_for_the_json(monkeypatch):
    """At 800 tokens mimo spent the budget reasoning and returned empty content."""
    sent = {}

    class Reply:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"relevant": true}'}}]}

    def post(url, headers, json, timeout):
        sent.update(json)
        return Reply()

    monkeypatch.setattr(ai_client.requests, "post", post)
    monkeypatch.delenv("FINSCRAPE_AI_MAX_TOKENS", raising=False)
    assert ai_client._call_openai_proxy("p", "s") == {"relevant": True}
    assert sent["max_tokens"] >= 3000
