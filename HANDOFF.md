# Handoff — 12 Oct 2026

What changed on 12 Oct, what is live, and the one step still to do from the Windows PC.
`task.md` holds the open work and `notes.md` the facts; this file is the walk-in summary.
Delete it once item 3 below is done.

## 1. State

| Part | State |
|---|---|
| `master` | PRs #38–#43 merged, CI green (backend + Postgres, web, Playwright, e2e-live, images) |
| API (Render) | Running the new code. `/api/health` reads `ok`; migration `0013` applied |
| Worker (ingest Action) | Three production runs after the merges succeeded; `check_prod` passed (DB 36 MB) |
| Web (Cloudflare Pages) | **Not published.** winfin.pages.dev still serves the old 18-panel build |

## 2. Pull and set up

PowerShell, in the repo:

```powershell
git checkout master
git pull
uv sync -p 3.14 --group server --group dev
cd web
node --version        # Vite+ needs ^22.18.0 or ^24.11.0; upgrade Node first if older
npm ci                # web/ now runs on Vite+ (vp); the old node_modules will not work
cd ..
```

Gates (all green on 12 Oct):

```powershell
uv run -p 3.14 pytest -q                       # 663 cases; 688 with WORLDFIN_TEST_DATABASE_URL set
make lint; make fmt-check                      # or the ruff commands in the Makefile
uv run -p 3.14 pyright
uv run -p 3.14 python -m tests.server.selfcheck
cd web; npm run typecheck; npm run test; npm run build   # typecheck is now `vp check`
```

## 3. Publish the web app (the one open step)

Either way publishes the four-view dashboard.

**A. From GitHub (recommended: later web changes then deploy on push).**
1. Cloudflare dashboard → My Profile → API Tokens → create a token with
   *Account → Cloudflare Pages → Edit*. Note the Account ID from the Pages overview.
2. Add both as repo secrets and run the workflow:
   ```powershell
   gh secret set CLOUDFLARE_API_TOKEN
   gh secret set CLOUDFLARE_ACCOUNT_ID
   gh workflow run deploy-web.yml
   gh run watch
   ```

**B. By hand.**
```powershell
cd web
npx wrangler login
$env:VITE_API_BASE = "https://winfin-api.onrender.com"
npm run build
npx wrangler pages deploy dist --project-name=winfin --branch=main
```

**Check after publishing** (https://winfin.pages.dev/app/):
- Four tabs: Today, Tickers, Track record, Sources; the URL hash follows the tab.
- `#record`: Next day, +2 and +4 days vs SPY with 95% ranges, and the Scored calls table.
- `#tickers`: the top ticker is charted, with the calls that named it under the chart.
- Today → click a feed row: the inspector shows Outcome, Coverage, and *Ask the analyst
  council* (takes about a minute).
- Landing page (`/`): no Markets Live, Live TV or social sentiment cards.

Then delete this file and item 1 in `task.md`.

## 4. What changed on 12 Oct

**Logic (#38, #40, #42)**
- Score 0 is OBSERVE (was CAUTIOUS); migration `0013` relabelled 4,915 old rows.
- The previous session's price move no longer feeds the score; AI vs heuristic
  disagreement caps the score at ±2.
- Track record: equity curve in event order, drawdown from realized moves, hit rate per
  confidence bucket, new `/api/outcomes`.
- Correlations keep state in Postgres across one-shot runs (velocity spikes can fire), a
  fixed watch list makes silent_divergence possible, a story that names a ticker explains
  its move, up to three signals per type per run.
- Merges into events another source has not written yet are retried.
- Sources read STALE after 25 h (`WORLDFIN_SOURCE_STALE_MIN`, default 1500).
- Storylines cluster without Ollama (shared ticker plus headline overlap), so scenarios
  group several events.

**Removed (#38, #43)**
- Legacy `dashboard/` D1 app and its scripts; quote boards, live TV, news lobby, agent and
  sentiment panels with their routes; the Reddit job and `social_posts` table.
- 122 unreachable `finscrape` modules, the root `main.py` CLI, and the `/api/v1` routers
  (one took unauthenticated POSTs).

**Tooling (#38, #39, #41)**
- CI: shared Python setup action, read-only token, superseded PR runs cancelled, all
  three images built on PRs, backup pulls postgres from ECR.
- `web/` on Vite+ 1.1.0: `vp dev`, `vp build`, `vp test run`, `vp check`.
- `deploy-web` Action publishes to Pages once the Cloudflare secrets exist.

## 5. Worth knowing

- Backup run **38281322368** (encrypted artifact, kept 14 days) holds the database from
  just before migration `0013`. Restore steps are in `docs/DEPLOY.md`.
- The ingest cron still runs daily at 00:10 UTC; `make ingest-every HOURS=1` switches to
  hourly for demos.
- CI only runs for PRs into `master`; a PR based on another branch gets no checks.
