"""The analysis pool is bounded, concurrent and order-preserving (plan M3.2).

The model call is the slow half of an ingest cycle and it is network-bound, so articles
from one source can be analysed together. These tests use a fake pipeline (no model, no
DB) and prove the three properties that matter: work overlaps, the results keep the
article order, and `WORLDFIN_ANALYZE_WORKERS=1` really is the old sequential loop.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from worker import runner


class _Event:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self.affected_entities: list[dict] = []

    def to_dict(self) -> dict:
        return {"subject": self.subject}


class _Pipeline:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.threads: set[int] = set()
        self.subjects: list[str] = []

    def _analyze_article(self, source_name: str, article) -> _Event:
        self.threads.add(threading.get_ident())
        self.subjects.append(article.title)
        if self.delay:
            time.sleep(self.delay)
        return _Event(article.title)

    def ai_failed(self) -> bool:
        return False

    def merged_into(self) -> None:
        return None


def _worker(monkeypatch, workers: int, delay: float = 0.0):
    monkeypatch.setattr(runner, "geocode_event", lambda *a, **k: (0.0, 0.0))
    w = runner.Worker.__new__(runner.Worker)
    w.enrichers = {}
    w.analyze_workers = workers
    w.pipeline = _Pipeline(delay=delay)
    items = [
        (SimpleNamespace(url=f"u{i}", title=f"story {i}", source="world/reuters"), None)
        for i in range(4)
    ]
    return w, items


def test_the_worker_count_is_bounded_and_reads_one_variable(monkeypatch):
    monkeypatch.delenv("WORLDFIN_ANALYZE_WORKERS", raising=False)
    assert runner._analyze_workers() == 6
    for raw, expected in [("1", 1), ("2", 2), ("0", 1), ("99", 8), ("", 6), ("x", 6)]:
        monkeypatch.setenv("WORLDFIN_ANALYZE_WORKERS", raw)
        assert runner._analyze_workers() == expected, raw


def test_four_articles_overlap_in_two_workers(monkeypatch):
    w, items = _worker(monkeypatch, workers=2, delay=0.25)

    started = time.perf_counter()
    dicts, _merges, judged = w._analyze_blocking("world/reuters", items)
    elapsed = time.perf_counter() - started

    # 4 × 0.25 s serial = 1.0 s; two workers must land near 0.5 s.
    assert elapsed < 0.8, elapsed
    assert len(w.pipeline.threads) == 2, w.pipeline.threads
    assert [d["subject"] for d in dicts] == [f"story {i}" for i in range(4)]
    assert judged == [f"u{i}" for i in range(4)]


def test_sentinels_run_on_one_thread_when_workers_is_one(monkeypatch):
    w, items = _worker(monkeypatch, workers=1, delay=0.01)

    dicts, _merges, judged = w._analyze_blocking("world/reuters", items)

    assert len(w.pipeline.threads) == 1, w.pipeline.threads
    assert [d["subject"] for d in dicts] == [f"story {i}" for i in range(4)]
    assert judged == [f"u{i}" for i in range(4)]


def test_a_failed_article_does_not_stop_the_batch(monkeypatch):
    w, items = _worker(monkeypatch, workers=2)
    calls = {"n": 0}

    def flaky(source_name, article):
        calls["n"] += 1
        if article.title == "story 1":
            raise RuntimeError("model exploded")
        return _Event(article.title)

    monkeypatch.setattr(w.pipeline, "_analyze_article", flaky)

    dicts, _merges, judged = w._analyze_blocking("world/reuters", items)

    assert [d["subject"] for d in dicts] == ["story 0", "story 2", "story 3"]
    assert "u1" not in judged  # a failed analysis is retried next cycle
    assert calls["n"] == 4
