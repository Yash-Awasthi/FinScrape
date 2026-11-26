"""Secret rotation without downtime: the old value stays valid for one window.

An API key and the Telegram webhook secret both rotate by adding the new value as the
primary and keeping the old one as `*_PREVIOUS` until every caller has moved. The tests
pin the overlap and the removal, so a rotation cannot become an outage or a permanent
second key.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from server.auth import require_api_key
from server.routes.telegram import _webhook_authentic
from server.settings import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _api_key_env(monkeypatch, current: str, previous: str = "") -> None:
    monkeypatch.setenv("FINSCRAPE_API_KEY", current)
    if previous:
        monkeypatch.setenv("FINSCRAPE_API_KEY_PREVIOUS", previous)
    else:
        monkeypatch.delenv("FINSCRAPE_API_KEY_PREVIOUS", raising=False)


def _telegram_env(monkeypatch, current: str, previous: str = "") -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", current)
    if previous:
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_PREVIOUS", previous)
    else:
        monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET_PREVIOUS", raising=False)


def _accepts(key: str | None) -> bool:
    try:
        asyncio.run(require_api_key(x_api_key=key, authorization=None))
    except HTTPException:
        return False
    return True


def test_both_keys_work_during_the_overlap(monkeypatch):
    _api_key_env(monkeypatch, "new-key", "old-key")
    assert _accepts("new-key")
    assert _accepts("old-key")
    assert not _accepts("other-key")
    assert not _accepts(None)


def test_removing_the_previous_key_ends_the_overlap(monkeypatch):
    _api_key_env(monkeypatch, "new-key")
    assert _accepts("new-key")
    assert not _accepts("old-key")


def test_an_empty_previous_key_does_not_accept_an_empty_header(monkeypatch):
    _api_key_env(monkeypatch, "new-key", "")
    assert not _accepts("")
    assert not _accepts(None)


def test_telegram_accepts_both_secrets_during_the_overlap(monkeypatch):
    _telegram_env(monkeypatch, "new-secret", "old-secret")
    assert _webhook_authentic("new-secret")
    assert _webhook_authentic("old-secret")
    assert not _webhook_authentic("other-secret")
    assert not _webhook_authentic(None)


def test_telegram_overlap_ends_when_previous_is_cleared(monkeypatch):
    _telegram_env(monkeypatch, "new-secret")
    assert _webhook_authentic("new-secret")
    assert not _webhook_authentic("old-secret")


def test_telegram_is_inert_with_no_secret(monkeypatch):
    _telegram_env(monkeypatch, "")
    assert not _webhook_authentic("")
    assert not _webhook_authentic("anything")
