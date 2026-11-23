"""Time a 6-article analysis cycle with and without the bounded pool (plan M3.2).

The real pipeline runs (relevance gate, spaCy, tickers, scoring); only the model call is
replaced by a fixed sleep, because the number this measures is how the network wait
scales — the part a pool can overlap. Latency is a parameter so the result can be read
for a fast or a slow provider instead of being true for one free model on one day.

    python -m scripts.bench_analysis --articles 6 --latency 0.5
    python -m scripts.bench_analysis --articles 6 --latency 13      # DEPLOY.md p50
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time

os.environ.setdefault("FINSCRAPE_LAYA", "0")

from finscrape import pipeline as pipeline_module
from finscrape.models import ScrapedArticle
from finscrape.pipeline import FinScrapePipeline
from worker import runner

REPLY = {
    "relevant": True,
    "verdict": "OBSERVE",
    "signal_score": 1,
    "confidence": 0.6,
    "reasoning": "Supply risk lifts energy names.",
    "sector_impact": "Energy",
    "tickers": ["XOM"],
    "magnitude": "medium",
    "novelty": "standard",
    "actionability": "medium",
    "affected_entities": [{"name": "Exxon Mobil", "ticker": "XOM"}],
    "second_order_effects": [],
    "key_metrics": {},
}


class _NullStore:
    @property
    def events(self) -> list[dict]:
        return []

    def add_event(self, event: dict) -> int:
        return 1

    def update_event(self, event_id: int, **kwargs: object) -> None:
        return None


def _article(i: int) -> ScrapedArticle:
    return ScrapedArticle(
        url=f"https://example.com/{i}",
        title=f"Oil jumps as Hormuz shipping halts, update {i}",
        text=(
            "Crude oil futures rose after tanker traffic through the Strait of Hormuz "
            "halted. Exxon Mobil (XOM) and Chevron (CVX) gained as freight rates spiked. "
        )
        * 4,
        source="world/reuters",
        age_hours=1.0,
        raw_tickers=["XOM"],
    )


def _cycle(workers: int, articles: int, latency: float) -> float:
    def slow_call(*args, **kwargs):
        time.sleep(latency)
        return dict(REPLY)

    pipeline_module.call_ai = slow_call
    runner.geocode_event = lambda *a, **k: (
        0.0,
        0.0,
    )  # keep the measurement off the geocoder

    worker = runner.Worker.__new__(runner.Worker)
    worker.enrichers = {}
    worker.analyze_workers = workers
    worker.pipeline = FinScrapePipeline(_NullStore())
    items = [(_article(i), None) for i in range(articles)]

    started = time.perf_counter()
    dicts, _merges, _judged = worker._analyze_blocking("world/reuters", items)
    elapsed = time.perf_counter() - started
    assert len(dicts) == articles, (
        f"{len(dicts)} of {articles} articles produced an event"
    )
    return elapsed


def bench(
    articles: int = 6, latency: float = 0.5, workers: int = 4, repeat: int = 3
) -> dict:
    # Warm the process once (model-free): the first pipeline run pays for lazily-built
    # ticker/company indexes, and counting that as "sequential is slow" would flatter
    # the pool. Then alternate the two modes so neither gets the warm cache only.
    _cycle(1, 1, 0.0)
    serial: list[float] = []
    pooled: list[float] = []
    for _ in range(repeat):
        serial.append(_cycle(1, articles, latency))
        pooled.append(_cycle(workers, articles, latency))
    serial_s = statistics.median(serial)
    pooled_s = statistics.median(pooled)
    return {
        "articles": articles,
        "model_latency_s": latency,
        "workers": workers,
        "sequential_s": round(serial_s, 2),
        "pooled_s": round(pooled_s, 2),
        "speedup": round(serial_s / pooled_s, 2) if pooled_s else 0.0,
        "serial_model_floor_s": round(articles * latency, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=int, default=6)
    parser.add_argument("--latency", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args(argv)

    result = bench(args.articles, args.latency, args.workers, args.repeat)
    print(
        f"bench_analysis: {result['articles']} articles, {result['model_latency_s']} s "
        f"model latency, {result['workers']} workers"
    )
    print(
        f"  sequential {result['sequential_s']} s (model floor {result['serial_model_floor_s']} s)"
    )
    print(f"  pooled     {result['pooled_s']} s")
    print(f"  speedup    {result['speedup']}x")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
