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

### 10x read traffic: no break point from this machine (plan M6.3.3)

`docs/LOAD.md` owns the operational load table. This records why the 10x break point is
still open: the driver and the server share one 8-core laptop, so client and server cannot
be separated, and a no-op endpoint breaks at the top rate.

Method: one `uvicorn server.main:app --workers 1` on 127.0.0.1, `WORLDFIN_RATE_LIMIT_PER_MIN=0`,
local Postgres on 127.0.0.1:5433, asyncpg pool 2-10. An open-loop Go driver schedules one
request every 1/rps seconds, 45 s timeout, 6000-connection pool. httpx is not usable as the
driver here: its client pool measures itself before it measures the server (500 rps gave
p50 24.7 s with `max_connections=2000`; the Go driver on the same box gave p50 0.3 s).
Rates are total across the listed endpoints, 50 rps being the 1x baseline.

| Run | Requests | 5xx | p50 | p95 | max |
|---|---|---|---|---|---|
| `/health`, 250 rps, 3 s | 750 | 0 | 3 ms | 4 ms | 8 ms |
| `/health`, 500 rps, 3 s | 1500 | 0 | 424 ms | 3613 ms | 4425 ms |
| `/api/events?limit=50`, 200 rps, 6 s | 1200 | 0 | 4 ms | 166 ms | 412 ms |
| `/api/scenarios`, 200 rps, 6 s | 1200 | 0 | 3 ms | 14 ms | 55 ms |
| events+scenarios, 200 rps, 10 s, run 1 | 2000 | 0 | 873 ms | 8414 ms | 11208 ms |
| events+scenarios, 200 rps, 10 s, run 2 | 2000 | 0 | 5 ms | 123 ms | 321 ms |
| events+scenarios, 250 rps, 10 s, run 1 | 2500 | 0 | 59 ms | 464 ms | 1542 ms |
| events+scenarios, 250 rps, 10 s, run 2 | 2500 | 0 | 186 ms | 2471 ms | 6219 ms |
| all three reads, 500 rps, 6 s | 3000 | 0 | 316 ms | 5321 ms | 7782 ms |

At the 50 rps baseline nothing breaks: p95 7 ms on events, 5 ms on scenarios, 0 5xx at
every rate tested up to 500 rps. Two facts then rule out a published ceiling. Identical
runs disagree by 68x - same rate, endpoints and process, p95 8414 ms then 123 ms at 200
rps - which is scheduler and loopback variance, not capacity. And `/health` returns a
constant yet spends p95 3.6 s at 500 rps, so the target rate saturates the accept path
before the application is the limit.

What is repeatable: each DB-backed read endpoint serves 200 rps at p95 <= 166 ms without
errors. That is a measured floor, not a break point.

`/api/market/quotes` is excluded from every conclusion: it stalls for about 8 s at every
rate, including 5 rps (max 8037 ms), because the yfinance upstream is refusing connections
on this host, so any mixed run measures that outage.

Getting the number the plan asks for needs the same driver on a second host against a
deployed instance. Raw runs: `.fleet/evidence/FinScrape/m6.3.3-load-10x.md`.

Re-run 2026-11-26 with k6 2.4.0 (`ops/loadtest/read.js`, constant-arrival-rate): 50 rps
held at 49.1 rps achieved, 0 dropped, p95 343 ms events and 101 ms scenarios. At a 500 rps
target `/health` reached 237.1 of 2500 scheduled iterations (443 dropped) at p95 5.6 s, and
events+scenarios reached 144.6 rps (755 dropped) at p95 8.8 s and 10.7 s, while the server
stayed up and answered 200. Windows also hit its pagefile/commit limit under the driver
(0xC000012D). The ceiling is still the machine, not the application.


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
