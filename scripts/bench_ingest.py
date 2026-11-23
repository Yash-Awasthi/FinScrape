"""Time the CPU half of one ingest cycle, and whether threads scale it (plan M3.1).

    python -m scripts.bench_ingest                     # 6 articles, sequential vs 4 threads
    python -m scripts.bench_ingest --articles 12 --workers 4 --repeat 5
    python -m scripts.bench_ingest --json bench.json

This is the measurement the free-threaded question needs. The ingest cycle is four CPU
stages per article — extract the body (trafilatura/lxml), pull entities (spaCy), pick a
sector (Laya or the keyword layer), and score the call — and they are CPU-bound, so:

* under the GIL a thread pool gains nothing (the work serialises), and
* under a free-threaded build it can gain real time *if* the native extensions in the way
  actually release the lock.

So the number to read is `speedup`: total wall time sequential ÷ total wall time with
`--workers` threads. Anything near 1.0 means threads are not worth the complexity here.

Offline and deterministic: the article set is `tests/fixtures/extraction/*.html`, no
network, no model downloads (spaCy's small English model only), and `FINSCRAPE_LAYA=0`
skips the classifier so the run is repeatable on a machine without the weights.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "extraction"


def _pages(limit: int) -> list[tuple[str, str]]:
    """(path, html) for the fixture set, cycled if `limit` is larger than the set."""
    files = sorted(FIXTURES.glob("*.html"))
    if not files:
        raise SystemExit(f"no fixtures in {FIXTURES}")
    return [(f.name, f.read_text(encoding="utf-8")) for f in (files * 4)[:limit]]


def _one_article(html: str) -> dict[str, float]:
    """The four stages for one article, each timed. Raises the stage's own error."""
    import trafilatura

    from finscrape.analysis.fallback import analyze_without_llm
    from finscrape.analysis.nlp import analyze_financial_text

    timings: dict[str, float] = {}

    started = time.perf_counter()
    body = trafilatura.extract(html) or ""
    timings["extract"] = time.perf_counter() - started

    title = body.splitlines()[0] if body else ""

    started = time.perf_counter()
    nlp = analyze_financial_text(title, body)
    timings["entities"] = time.perf_counter() - started

    started = time.perf_counter()
    if os.getenv("FINSCRAPE_LAYA", "1") != "0":
        from finscrape.analysis.laya import choose_sector, classify

        choose_sector("", classify(title, body), "other", ())
    timings["sector"] = time.perf_counter() - started

    started = time.perf_counter()
    analyze_without_llm(title, body, nlp)
    timings["score"] = time.perf_counter() - started

    timings["total"] = sum(
        timings[key] for key in ("extract", "entities", "sector", "score")
    )
    return timings


def sequential(pages: list[tuple[str, str]]) -> list[dict[str, float]]:
    return [_one_article(html) for _name, html in pages]


def threaded(pages: list[tuple[str, str]], workers: int) -> list[dict[str, float]]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_one_article, (html for _name, html in pages)))


def summarise(runs: list[list[dict[str, float]]]) -> dict[str, float]:
    """Median wall time of the whole batch, plus the median per stage."""
    totals = [sum(t["total"] for t in run) for run in runs]
    stages = {
        stage: statistics.median([sum(t[stage] for t in run) for run in runs])
        for stage in ("extract", "entities", "sector", "score")
    }
    return {
        "batch_s": round(statistics.median(totals), 3),
        **{k: round(v, 3) for k, v in stages.items()},
    }


def bench(articles: int = 6, workers: int = 4, repeat: int = 3) -> dict:
    pages = _pages(articles)
    # One warm-up pass: the first spaCy call loads the model, which is a start-up cost,
    # not a per-article cost. Timing it would describe process boot, not ingest.
    _one_article(pages[0][1])

    serial = summarise([sequential(pages) for _ in range(repeat)])
    parallel = summarise([threaded(pages, workers) for _ in range(repeat)])
    speedup = serial["batch_s"] / parallel["batch_s"] if parallel["batch_s"] else 0.0
    return {
        "python": sys.version.split()[0],
        "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
        "articles": articles,
        "workers": workers,
        "repeat": repeat,
        "sequential": serial,
        "threaded": parallel,
        "speedup": round(speedup, 2),
        "per_article_s": round(serial["batch_s"] / articles, 3),
    }


def verdict(result: dict) -> str:
    """What the numbers mean, in the words the plan needs."""
    if result["speedup"] < 1.15:
        return (
            f"threads do not help here (speedup {result['speedup']}x with "
            f"{result['workers']} workers): these stages hold the GIL, so a free-threaded "
            "build buys nothing for the ingest cycle and the sequential loop stays"
        )
    return (
        f"threads are worth it (speedup {result['speedup']}x with {result['workers']} workers): "
        "consider a bounded pool for article analysis (plan M3.2)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--articles", type=int, default=6, help="articles in the batch")
    parser.add_argument(
        "--workers", type=int, default=4, help="threads for the parallel pass"
    )
    parser.add_argument("--repeat", type=int, default=3, help="timed repeats per mode")
    parser.add_argument("--json", default="", help="write the raw result here")
    args = parser.parse_args(argv)

    result = bench(args.articles, args.workers, args.repeat)
    print(
        f"bench_ingest: python {result['python']} "
        f"(gil {'enabled' if result['gil_enabled'] else 'disabled'}), "
        f"{result['articles']} articles, {result['repeat']} repeats"
    )
    print(
        f"  sequential {result['sequential']['batch_s']:.2f} s  "
        f"({result['per_article_s']:.2f} s/article)"
    )
    print(f"  {args.workers} threads {result['threaded']['batch_s']:.2f} s")
    for stage in ("extract", "entities", "sector", "score"):
        print(
            f"    {stage:9} {result['sequential'][stage] * 1000:7.0f} ms sequential  "
            f"{result['threaded'][stage] * 1000:7.0f} ms threaded"
        )
    print(f"  speedup {result['speedup']}x")
    print(f"  verdict: {verdict(result)}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
