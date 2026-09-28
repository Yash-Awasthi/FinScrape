# FinScrape — Complete Windows Setup Guide
# From zero to running dashboard, using PowerShell

===========================================================================
WHAT YOU WILL HAVE AT THE END
===========================================================================

  Terminal 1:  Ollama running Qwen 2.5 (the local AI)
  Terminal 2:  Dashboard at http://localhost:8787
  Terminal 3:  Scrape server at http://localhost:5001
  Terminal 4:  Push script — scrapes news, scores with AI, pushes to dashboard

  No cloud APIs needed. No Cloudflare account needed. Everything local.

===========================================================================
STEP 0 — PREREQUISITES (install once, never again)
===========================================================================

Open PowerShell as Administrator for each of these.

--- 0A. Python 3.11+ ---
Check if you have it:
  python --version

If not 3.11+, download from: https://www.python.org/downloads/
  ✓ During install: CHECK "Add Python to PATH"
  ✓ During install: CHECK "pip"

Verify after install (open a NEW PowerShell window):
  python --version       # should show 3.11.x or higher
  pip --version

--- 0B. Git ---
Check:
  git --version

If missing: https://git-scm.com/download/win
  ✓ During install: keep all defaults

--- 0C. Ollama (the local AI runtime) ---
Download and run the installer:
  https://ollama.com/download/windows

After installing, open a NEW PowerShell and verify:
  ollama --version

Then pull the Qwen 2.5 model (~4 GB download, do this once):
  ollama pull qwen2.5:7b

If you have less than 6 GB RAM free, use the smaller model instead:
  ollama pull qwen2.5:3b
  (then use qwen2.5:3b everywhere qwen2.5:7b appears below)

--- 0D. Bun (for the dashboard) ---
In PowerShell (as Administrator):
  powershell -c "irm bun.sh/install.ps1 | iex"

Open a NEW PowerShell and verify:
  bun --version

===========================================================================
STEP 1 — CLONE THE REPO
===========================================================================

In PowerShell (normal, not Administrator):

  cd $HOME
  git clone https://github.com/Yash-Awasthi/fin-scrape.git
  cd fin-scrape

===========================================================================
STEP 2 — PYTHON VIRTUAL ENVIRONMENT
===========================================================================

Still in the fin-scrape folder:

  python -m venv venv
  .\venv\Scripts\Activate.ps1

You should now see (venv) at the start of your prompt.

If you get an error about execution policy, run this first:
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Then try the Activate line again.

Install all Python dependencies:
  pip install -r requirements.txt

This takes 3-5 minutes. Some packages compile C extensions — that is normal.

Install the browser engine (needed for some scrapers):
  python -m patchright install chromium

===========================================================================
STEP 3 — CONFIGURE .env
===========================================================================

Copy the example file to create your local config:
  Copy-Item .env.example .env

The .env file already has correct defaults for local Ollama.
Open it to verify (optional):
  notepad .env

It should look like this — no changes needed:
  OPENAI_BASE_URL=http://localhost:11434/v1
  OPENAI_API_KEY=ollama
  FINSCRAPE_MODEL=qwen2.5:7b
  FINSCRAPE_AI_TIMEOUT=180
  FINSCRAPE_DASHBOARD_URL=http://localhost:8787
  FINSCRAPE_API_KEY=local-dev-key

===========================================================================
STEP 4 — DASHBOARD SETUP
===========================================================================

In a NEW PowerShell window (keep the first one open):

  cd $HOME\fin-scrape\dashboard
  bun install

Create the local secrets file:
  New-Item -Name ".dev.vars" -ItemType File
  notepad .dev.vars

Paste this exactly into .dev.vars and save:
  API_KEY=local-dev-key
  TELEGRAM_BOT_TOKEN=

===========================================================================
STEP 5 — START EVERYTHING (4 terminals, run in order)
===========================================================================

Open 4 PowerShell windows. Run one command in each.

--- TERMINAL 1: Ollama AI ---
  ollama serve

Leave it running. You'll see "Listening on 127.0.0.1:11434"

--- TERMINAL 2: Dashboard ---
  cd $HOME\fin-scrape\dashboard
  bun run dev

Wait until you see "Ready on http://localhost:8787"
Open http://localhost:8787 in your browser — you'll see an empty dashboard.

--- TERMINAL 3: Scrape server (trigger button for dashboard) ---
  cd $HOME\fin-scrape
  .\venv\Scripts\Activate.ps1
  pip install flask        # first time only
  python scrape_server.py

You'll see:
  Scrape server running on http://localhost:5001
  Dashboard : http://localhost:8787
  Ollama    : http://localhost:11434/v1  model=qwen2.5:7b

--- TERMINAL 4: Smoke test (verify AI is working) ---
  cd $HOME\fin-scrape
  .\venv\Scripts\Activate.ps1
  python scripts\smoke_test_ollama.py

You should see all PASS. This confirms:
  ✓ Ollama is running and reachable
  ✓ Qwen 2.5 model is loaded
  ✓ call_ai() returns valid JSON with signal_score, impact_direction, etc.
  ✓ Cache is working

===========================================================================
STEP 6 — RUN YOUR FIRST SCRAPE
===========================================================================

In Terminal 4 (with venv active):

Quick test — 3 articles, no AI (fast, just to confirm scrapers work):
  python push_to_dashboard.py --no-ai --limit 3 --age-hours 6

Full run — scrapes Yahoo Finance, scores with Qwen 2.5, pushes to dashboard:
  python push_to_dashboard.py --limit 10 --age-hours 4

Watch Terminal 1 (Ollama) — you'll see model inference happening.
Watch Terminal 2 (Dashboard) — events appear in real time.

Open http://localhost:8787 — you'll see scored news events with:
  - INVEST / OBSERVE / CAUTIOUS / PULL_OUT verdicts
  - Signal scores from -5 to +5
  - Tickers, confidence, divergence flags
  - Real AI reasoning from Qwen 2.5

===========================================================================
STEP 7 — DAILY USE (once everything is set up)
===========================================================================

Every day you use FinScrape:

1. Open Terminal 1:
     ollama serve

2. Open Terminal 2:
     cd $HOME\fin-scrape\dashboard && bun run dev

3. Open Terminal 3:
     cd $HOME\fin-scrape
     .\venv\Scripts\Activate.ps1
     python scrape_server.py

4. Run a scrape whenever you want fresh data:
     python push_to_dashboard.py --limit 20 --age-hours 2

Or run one ingest cycle into Postgres:
     python -m worker.main --once

===========================================================================
COMMAND REFERENCE
===========================================================================

--- push_to_dashboard.py flags ---
  --limit 20          Max articles per source (default: 30)
  --age-hours 2       Only articles from last 2 hours (default: 2.0)
  --no-ai             Heuristic-only, skip Ollama (fast, less accurate)
  --concurrency 3     Parallel AI calls — speeds up large batches 3-4x
  --sources yahoo cnbc  Only scrape specific sources

Examples:
  python push_to_dashboard.py --limit 5 --age-hours 6 --no-ai
  python push_to_dashboard.py --limit 20 --concurrency 3
  python push_to_dashboard.py --sources yahoo cnbc --limit 10

--- worker ---
  python -m worker.main --once                            # one ingest cycle, then exit
  python -m worker.main                                   # every source on its interval

--- Ollama model management ---
  ollama list                    # see downloaded models
  ollama pull qwen2.5:3b         # smaller/faster model
  ollama pull qwen2.5:14b        # larger/smarter model (needs ~10 GB RAM)

To use a different model, edit .env:
  FINSCRAPE_MODEL=qwen2.5:3b

===========================================================================
TROUBLESHOOTING
===========================================================================

Problem: "ollama serve" fails / port in use
  Fix: Ollama may already be running as a background service after install.
       Try opening http://localhost:11434 in browser — if it responds, skip
       "ollama serve" (it's already running).

Problem: "python scripts\smoke_test_ollama.py" fails on "Qwen model present"
  Fix: ollama pull qwen2.5:7b   (model not downloaded yet)

Problem: "Connection refused" on port 11434
  Fix: Start Ollama first (Terminal 1), wait 5 seconds, then run the test.

Problem: pip install fails on curl_cffi or lxml (C compilation error)
  Fix: Install Visual C++ Build Tools from:
       https://visualstudio.microsoft.com/visual-cpp-build-tools/
       Select "Desktop development with C++" workload, then retry pip install.

Problem: "Execution Policy" error on Activate.ps1
  Fix: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

Problem: Dashboard shows "Unauthorized"
  Fix: Check .dev.vars has API_KEY=local-dev-key
       Check .env has FINSCRAPE_API_KEY=local-dev-key
       They must match.

Problem: Scrape returns 0 articles
  Fix: Try --age-hours 24 to widen the time window.
       Some sources (Bloomberg, FT) require subscriptions — use yahoo/cnbc/rss.

Problem: AI is very slow (>2 min per article)
  Fix: Switch to smaller model: set FINSCRAPE_MODEL=qwen2.5:3b in .env
       Or add --concurrency 2 to run 2 articles in parallel.
       CPU inference is slow — GPU (even integrated) helps significantly.

Problem: bun run dev fails with "wrangler: command not found"
  Fix: bun install   (run inside the dashboard/ folder)

Problem: push_to_dashboard.py shows "AI unavailable" in reasoning
  Fix: Check Terminal 1 (ollama serve) is running.
       Run python scripts\smoke_test_ollama.py to diagnose.

===========================================================================
WHAT EACH FILE DOES
===========================================================================

  worker/main.py            Ingest worker — scrapes + AI scores + saves to Postgres
  push_to_dashboard.py      Scrapes + AI scores + pushes to dashboard API
  scrape_server.py          Flask server — lets dashboard trigger scrapes via button
  scripts/smoke_test_ollama.py   Verify Ollama + AI pipeline is working

  finscrape/analysis/ai_client.py    Calls Ollama/Qwen, caches responses
  finscrape/analysis/validator.py    Heuristic scoring, divergence detection
  finscrape/analysis/prompts.py      LLM prompt templates
  finscrape/pipeline.py              Full AI+heuristic fusion logic
  finscrape/scrapers/                One file per news source

  dashboard/workers/app.ts           Cloudflare Worker (serves the UI + API)
  dashboard/app/                     React frontend
  .env                               Your local config (never committed)
  .env.example                       Template with correct defaults
