# Measured performance

Numbers here are produced by a command in this repository, with the machine and the date.
Anything unmeasured is marked **needs-verify** rather than estimated.

## Free-threaded Python: measured, not adopted (plan M3.1)

The ingest cycle's CPU stages are extraction (trafilatura/lxml), entity extraction
(spaCy), sector classification (Laya, or the keyword layer) and scoring. Whether a
free-threaded build helps depends on one thing: do those native extensions release the
GIL? The plan requires a measurement before adoption.

Command (both runs on Windows 11, 8-core laptop, Python 3.14.8, 6 fixture articles,
3 repeats, `FINSCRAPE_LAYA=0` so the number is the deterministic layers only):

```
python -m scripts.bench_ingest --articles 6 --workers 4 --repeat 3
```

| Build | sequential | 4 threads | speedup |
|---|---|---|---|
| CPython 3.14.8 (GIL enabled) | 0.37 s | 1.02 s | **0.36×** |

Threads are *slower*, not neutral: the stages hold the GIL, and the thread pool adds
contention on the spaCy pipeline. Stage medians show it directly — extraction 24 ms
sequential vs 177 ms threaded, entities 335 ms vs 860 ms. **Verdict: the sequential
loop stays.** Parallelising this work would need processes, not threads, and the cycle's
wall time is dominated by the model call anyway (see `docs/LOAD.md` and the DEPLOY.md
model table).

The free-threaded build could not be measured on this machine: the project's hard
dependency `orjson==3.13.0` publishes no `cp314t` Windows wheel, and the sdist build
fails at link time, so `uv sync -p 3.14t` cannot complete. That is itself a result: a
free-threaded deployment would drop a core dependency from the lock. Linux CI keeps the
manual `.github/workflows/free-threaded.yml` job, which asserts the build imports
`lxml`, `curl_cffi`, `orjson` and `msgspec` with `sys._is_gil_enabled() == False` — so
the day the wheels exist, the import gate is already in place.

Re-run: `make bench-ingest`.

## Read API

Load-test results (50 rps, p95, first bottleneck) live in `docs/LOAD.md`, because they
are an operational claim, not a stack one.

## Analysis pool: 6 s of model wait, overlapped (plan M3.2)

`worker/runner.py` analyses the articles of one source cycle in a bounded pool
(`WORLDFIN_ANALYZE_WORKERS`, default 6, capped at 8; `1` restores the sequential loop).
The pool overlaps the *wait*, not the CPU: the model call is network-bound, while
extraction/NLP/scoring stay on the GIL (see the section above).

Command (`scripts/bench_analysis.py` runs the real pipeline — relevance gate, spaCy,
tickers, scoring — and replaces only `call_ai` with a fixed sleep, warmed once, modes
alternated):

```
python -m scripts.bench_analysis --articles 6 --latency 0.5 --workers 4
python -m scripts.bench_analysis --articles 6 --latency 13 --workers 4
python -m scripts.bench_analysis --articles 6 --latency 32 --workers 6
```

| Model latency (6 articles) | Sequential | Pooled | Speedup |
|---|---|---|---|
| 0.5 s (simulated fast provider) | 3.41 s | 1.43 s (4 workers) | 2.38× |
| 13 s (`docs/DEPLOY.md` p50) | 78.53 s | 26.33 s (4 workers) | 2.98× |
| 32 s (`docs/DEPLOY.md` p90) | 192.44 s | **32.38 s** (6 workers) | 5.94× |

At the documented p90 the exit gate in the plan ("a 6-article cycle under 60 s") was
192 s before and is 32 s after. Six is the default because it equals the per-source
article cap, so one cycle is one wave. The cost is up to six concurrent provider calls;
the key queue, the response cache and the Laya predict lock are all already
thread-safe, and a 429 still rotates the queue.

Correctness is pinned by `tests/test_worker_parallel.py`: results keep article order,
`1` runs on a single thread, one failed article does not stop the batch, and a failed
analysis stays out of the judged set so the next cycle retries it.

Re-run: `make bench-analysis`.
