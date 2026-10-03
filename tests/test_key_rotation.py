"""Keys form a queue: one that answers 429 moves to the back and the next takes over."""

from types import SimpleNamespace

from finscrape.analysis import ai_client

OK = {"choices": [{"message": {"content": '{"relevant": true}'}}]}


def _proxy(monkeypatch, spent: set[str]) -> list[str]:
    used: list[str] = []

    def post(url, headers, **_):
        key = headers["Authorization"].removeprefix("Bearer ")
        used.append(key)
        code = 429 if key in spent else 200
        return SimpleNamespace(status_code=code, text="", json=lambda: OK)

    monkeypatch.setattr(ai_client.requests, "post", post)
    monkeypatch.setattr(ai_client, "_moved_at", {})
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEYS", "b, c")
    return used


def test_429_moves_the_key_to_the_back(monkeypatch):
    used = _proxy(monkeypatch, spent={"a", "b"})
    assert ai_client._call_openai_proxy("p", "s") == {"relevant": True}
    assert ai_client._call_openai_proxy("p", "s") == {"relevant": True}
    assert used == ["a", "b", "c", "c"]
    assert ai_client._proxy_keys() == ["c", "a", "b"]


def test_spent_keys_come_back_after_the_rest(monkeypatch):
    used = _proxy(monkeypatch, spent={"a", "b", "c"})
    assert ai_client._call_openai_proxy("p", "s") is None
    assert ai_client._call_openai_proxy("p", "s") is None
    assert used == ["a", "b", "c", "a", "b", "c"]


def test_single_key_survives_429(monkeypatch):
    used = _proxy(monkeypatch, spent={"a"})
    monkeypatch.delenv("OPENAI_API_KEYS")
    assert ai_client._call_openai_proxy("p", "s") is None
    assert ai_client._call_openai_proxy("p", "s") is None
    assert used == ["a", "a"]


def test_loaded_order_skips_a_key_spent_last_run(monkeypatch):
    used = _proxy(monkeypatch, spent={"a"})
    ai_client.load_key_moves({ai_client.key_fingerprint("a"): 100.0})
    assert ai_client._call_openai_proxy("p", "s") == {"relevant": True}
    assert used == ["b"]
