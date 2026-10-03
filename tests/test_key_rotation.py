"""A key whose free allowance is spent (HTTP 429) hands over to the next key."""

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
    monkeypatch.setattr(ai_client, "_spent_keys", set())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEYS", "b, c")
    return used


def test_429_rotates_and_remembers(monkeypatch):
    used = _proxy(monkeypatch, spent={"a", "b"})
    assert ai_client._call_openai_proxy("p", "s") == {"relevant": True}
    assert ai_client._call_openai_proxy("p", "s") == {"relevant": True}
    assert used == ["a", "b", "c", "c"]


def test_last_key_is_never_retired(monkeypatch):
    used = _proxy(monkeypatch, spent={"a", "b", "c"})
    assert ai_client._call_openai_proxy("p", "s") is None
    assert ai_client._call_openai_proxy("p", "s") is None
    assert used == ["a", "b", "c", "c"]


def test_single_key_survives_429(monkeypatch):
    used = _proxy(monkeypatch, spent={"a"})
    monkeypatch.delenv("OPENAI_API_KEYS")
    assert ai_client._call_openai_proxy("p", "s") is None
    assert ai_client._call_openai_proxy("p", "s") is None
    assert used == ["a", "a"]
