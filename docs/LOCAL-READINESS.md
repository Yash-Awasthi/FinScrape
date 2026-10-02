# Local readiness and zero-cost setup

The current application is the FastAPI `server/`, ingestion `worker/`, and Vite
`web/` dashboard. `dashboard/` and `SETUP_WINDOWS.md` describe the legacy app.
Current work is tracked in [task.md](../task.md).

## Requirements

- Python 3.13 and uv.
- Node 24 and npm.
- PostgreSQL 16/17 for integration tests or a seeded backend.
- Playwright's matching Chromium headless shell for browser tests.
- GNU Make is convenient; equivalent commands are listed below.

No paid API, cloud account, model download, Redis, or GPU is needed for these
checks. Ollama and live ingestion are optional and were not exercised.
Dependency/browser downloads need internet access but no service subscription.
Docker is an alternative for the demo, not a prerequisite for native checks.

## Install in a fresh checkout

```powershell
uv sync --locked -p 3.13 --group server --group dev
Push-Location web
npm ci
$env:PLAYWRIGHT_SKIP_BROWSER_GC = '1'
node node_modules/@playwright/test/cli.js install chromium --only-shell
Pop-Location
```

## Isolated database tests (PowerShell)

Do not point tests at application data: integration fixtures deliberately truncate
tables. A `_test` suffix is required but does not itself prove a database is safe.
Use a new cluster with an unused loopback port. This recipe does not connect to the
existing Windows PostgreSQL service or require its password.

Run from the repository root, in a dedicated shell:

```powershell
$pg = 'C:\Program Files\PostgreSQL\17\bin'
$cluster = Join-Path $env:LOCALAPPDATA ('Temp\worldfin-test-' + [guid]::NewGuid())
$port = 55439
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $port is already occupied"
}
& "$pg\initdb.exe" -D $cluster -U worldfin --auth=trust --encoding=UTF8 --no-locale
if ($LASTEXITCODE -ne 0) { throw 'initdb failed' }
& "$pg\pg_ctl.exe" -D $cluster -l "$cluster.log" -o "-h 127.0.0.1 -p $port" -w start
if ($LASTEXITCODE -ne 0) { throw 'temporary PostgreSQL startup failed' }
try {
    & "$pg\createdb.exe" -h 127.0.0.1 -p $port -U worldfin -w worldfin_readiness_test
    if ($LASTEXITCODE -ne 0) { throw 'temporary database creation failed' }

    Get-ChildItem Env: | Where-Object {
        $_.Name -match '^(WORLDFIN_|FINSCRAPE_|OPENAI_|OPENROUTER_|TELEGRAM_)'
    } | ForEach-Object { Remove-Item ('Env:' + $_.Name) }
    $env:PYTHON_DOTENV_DISABLED = '1'
    $env:OLLAMA_HOST = 'http://127.0.0.1:9'
    $env:WORLDFIN_TEST_DATABASE_URL = "postgresql://worldfin@127.0.0.1:$port/worldfin_readiness_test"
    $env:WORLDFIN_REQUIRE_PG = '1'
    make lint fmt-check typecheck selfcheck test 'PY=uv run --no-sync --offline'
    if ($LASTEXITCODE -ne 0) { throw 'backend gates failed' }
} finally {
    & "$pg\pg_ctl.exe" -D $cluster -m fast -w stop
}
```

Trust authentication here is for a temporary local-only cluster: any local user
can access it while running. Stop it after testing; this recipe retains its files
rather than deleting them. `tests/conftest.py` also disables dotenv loading and
Pydantic's `.env` file source. `WORLDFIN_REQUIRE_PG=1` makes missing PostgreSQL fail
instead of silently skipping integration coverage.

On this workstation, `task.md` reserves 8000, 5432, 6379, 3000, and 4173 for Nexus.
The recipe uses PostgreSQL port 55439 and browser preview port 4183.

### Without Make

After the same environment preparation, use `uv run --no-sync --offline` before
each command below. Lint and format paths are maintained as `NEW_DIRS` in the
root Makefile, which CI now invokes directly:

```text
ruff check server worker finscrape/scrapers/world finscrape/ingestors finscrape/scenarios.py tests/server tests/test_world_phase2.py tests/test_worker_phase3.py tests/test_correlate_phase4.py tests/test_scenarios.py tests/test_no_multi_model.py tests/live_e2e.py
ruff format --check server worker finscrape/scrapers/world finscrape/ingestors finscrape/scenarios.py tests/server tests/test_world_phase2.py tests/test_worker_phase3.py tests/test_correlate_phase4.py tests/test_scenarios.py tests/test_no_multi_model.py tests/live_e2e.py
pyright
python -m tests.server.selfcheck
pytest -q
```

## Frontend and local-only browser checks

```powershell
Push-Location web
npm run typecheck
npm run test
npm run build
$env:CI = '1'
node node_modules/@playwright/test/cli.js test --workers=2
Pop-Location
```

The browser configuration builds the SPA and starts its own strict-port preview
at `127.0.0.1:4183`. `CI=1` forbids reusing an existing server. REST and WebSocket
responses are fixtures; nonlocal browser HTTP requests are blocked, including
third-party images/media. No live API or existing project data is needed.
The tests cover panel visibility, globe canvas, event/inspector interaction,
keyboard navigation, and a WebSocket update.

The direct Playwright command avoids an observed npm 12 argument-forwarding
failure with `npm run e2e -- --workers=2`. The normal package script remains intact.

For an interactive seeded demo, the [README](../README.md#-quick-start) documents
`make demo` and the native API/web startup. Run that in a fresh disposable setup:
the worker fetches live data and application startup normally reads `.env`.
It is a separate workflow from the isolated offline checks above.

## Real browser-to-API integration

The existing `web/e2e-live/fullstack.spec.ts` now runs through the real built SPA,
Vite proxy, FastAPI routes, SQL queries, migrations, and curated seed loader.
Its original assertions remain intact: the Hormuz event appears with XOM,
selection populates the inspector with Oil majors, and scenario cards display a
probability. No API responses are replaced with fixtures in this suite.

In the database recipe above, insert this block **before** `make ... test`, while
the new database is still empty and PostgreSQL is running:

```powershell
$env:CI = '1'
Push-Location web
try {
    node node_modules/@playwright/test/cli.js test -c playwright.live.config.ts --workers=1
    if ($LASTEXITCODE -ne 0) { throw 'real-API browser test failed' }
} finally {
    Pop-Location
}
```

The `WORLDFIN_TEST_DATABASE_URL` must use literal `127.0.0.1`, an explicit port,
and a database ending in `_test`, without query parameters. The launcher refuses
any database already containing user tables, rather than resetting it. For each
rerun, create another new test database in your disposable cluster; never point
this command at an existing application database. CI's dedicated service database
is already fresh and now uses the same explicit loopback address.

Isolation is implemented only in test code:

- `tests/live_e2e.py` retains only OS runtime environment variables and the
  explicitly supplied test DSN. It clears provider credentials, proxy settings,
  ambient database configuration and frontend VITE variables, redirects home and
  caches into a fresh temporary directory, disables python-dotenv, and disables
  Pydantic's dotenv source before importing application modules.
- API DNS and socket egress are denied except connections to the selected test
  database. Native libcurl's synchronous and asynchronous transfer entry points
  are also denied. API child process execution is denied. This is an integration
  test guard for the application's transports, not an OS-level hostile-code sandbox.
- Windows needs an internal loopback socketpair to construct an asyncio loop.
  The launcher creates that loop first, then enables the network guard; seed and
  Uvicorn run on that same loop. It does not allow arbitrary local services.
- `vite.live.config.ts` loads environment files only from the launcher's fresh
  empty directory. A regression test exposed that Vite 5 ignores `envDir: false`;
  the empty-directory implementation fixes that defect and is tested against a
  fake dotenv sentinel. The proxy target is pinned to `127.0.0.1:8012`.
- Browser HTTP requests outside `127.0.0.1:4184` are blocked. All local REST and
  WebSocket traffic remains real. Both API and preview prohibit server reuse;
  readiness uses `/ready`, and the preview requires an unused port.

Nine Python regression cases cover environment filtering, dotenv isolation, DSN
validation, actual network transport denial, and refusing a nonempty database
without changing its event count. A Vitest case checks dotenv isolation and the
real local proxy configuration. All are included in the full gates above.

## Blocked or untested

- External market/news/LLM paths are deliberately denied during live E2E. Their
  real-provider success, model quality and outbound notifications remain untested.
