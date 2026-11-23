# Onboarding: fresh clone → populated dashboard

Eight steps, about ten minutes on a machine with Docker. Each step says what you should
see, so a failure is obvious at the step that caused it rather than three steps later.
Nothing here needs an LLM key.

## 1. Clone and enter

```bash
git clone https://github.com/Yash-Awasthi/FinScrape.git
cd FinScrape
```

Expected: the repository root contains `Makefile`, `docker-compose.yml`, `finscrape/`,
`server/`, `worker/`, `web/`.

## 2. Check the tool versions

```bash
docker compose version     # >= 2.20
uv --version               # the Python half
node --version             # >= 22 for web/
```

Expected: three version lines, all at or above the numbers above. There is no separate
doctor command; the first real check is step 4. If `uv` is missing, [STACK.md](STACK.md)
names the exact pinned versions the project tests against.

## 3. Create your `.env`

```bash
cp .env.example .env
```

Expected: `.env` exists and `make ports-check` passes:

```console
$ make ports-check
ports-check: docker-compose.yml publishes no reserved port (4 checked)
```

That gate exists because the workstation already runs another stack on 8000/5432/6379/
3000/4173 — see [PORTS.md](PORTS.md). If it fails, set `WORLDFIN_API_HOST_PORT` or
`WORLDFIN_PG_HOST_PORT` in `.env` instead of editing the compose file.

## 4. Bring the stack up and seed it

```bash
make demo
```

This is `docker compose up -d --build` plus `python -m server.seed`. Expected, in order:

- Postgres healthy on `localhost:5433`;
- API healthy on `localhost:8010`;
- `server.seed` prints a JSON summary with `"events_inserted": 16`;
- the worker logs one cycle and stays up.

If the API container exits, `make logs` shows why; the usual cause is a taken port
(step 3) or a stale volume from an older schema: `docker compose down -v`, then repeat step 4.

## 5. Open the API

```bash
curl -s localhost:8010/health
```

Expected: `{"status":"ok","db":true,...}`. `/docs` at
<http://localhost:8010/docs> lists 24 paths.

## 6. Open the dashboard

<http://localhost:8080/app/>

Expected on Today: the Signal Feed with 16 rows, a globe with one column per event
(colored by verdict: INVEST/PULL_OUT/CAUTIOUS/OBSERVE all present), a calendar with
activity on at least five days, and the scenarios panel above the fold.

## 7. Walk the other three views

- **Tickers** — market strip, ticker suggestions, the candle chart; clicking a ticker
  chip in the feed lands here with that symbol charted.
- **Track record** — the accuracy panel has scored outcomes from the seed, not zeros.
- **Sources** — source health plus at least one correlation signal.

Expected: each view renders without an empty panel, and the URL hash matches the tab
(`#tickers`, `#record`, `#sources`).

## 8. Prove your checkout is green

```bash
make verify
```

Expected tail:

```console
verify: all non-browser gates green
```

`make verify` is `make ci` minus the browser E2E: lint, format check, typecheck, pyright
baseline, selfcheck, OpenAPI contract, the pytest suite, the web gates and the eval gate.
It is the pre-push gate; CI adds Playwright on top. The first run installs dependencies
and takes a few minutes; later runs are much faster.

## Where to go next

| Question | File |
|---|---|
| How a story becomes a row | [INGEST.md](INGEST.md) |
| Why the stack looks like this | [STACK.md](STACK.md) |
| Why the model choice is measured, not asserted | [EVAL.md](EVAL.md) |
| Deploy, warm, restore, rotate keys | [DEPLOY.md](DEPLOY.md), [RUNBOOK.md](RUNBOOK.md) |
| What the track-record numbers mean | [CALIBRATION.md](CALIBRATION.md) |
