# FinScrape developer commands. `make help` lists them.
# Python tasks run via uv pinned to 3.14 with the server + dev groups so
# FastAPI/asyncpg/ruff are present.
.DEFAULT_GOAL := help
PY := uv run -p 3.14 --group server --group dev
COMPOSE := docker compose

# New (FinScrape) code is held to ruff *formatting* too; pre-existing finscrape source
# isn't format-clean, so `fmt`/`fmt-check` stay scoped. Lint itself covers the whole tree:
# `ruff check .` is gated against the per-file allowlist in ruff-baseline.toml.
NEW_DIRS := server worker finscrape/fetchers finscrape/settings.py finscrape/extract finscrape/signals \
	tests/server tests/test_world_phase2.py tests/test_worker_phase3.py \
	tests/test_correlate_phase4.py tests/test_scenarios.py tests/test_no_multi_model.py tests/live_e2e.py \
	scripts/backfill scripts/repo_facts.py scripts/ruff_baseline.py scripts/pyright_baseline.py \
	scripts/eval_model.py scripts/openapi_snapshot.py scripts/postman.py scripts/explain.py \
	scripts/check_ports.py \
	scripts/bench_analysis.py \
	tests/test_backfill.py tests/test_call_tuning.py tests/test_bandit.py tests/test_weekly.py \
	tests/test_full_text_enrich.py tests/test_check_prod.py tests/test_key_rotation.py \
	tests/server/test_key_queue.py tests/test_repo_facts.py tests/test_docs.py \
	tests/test_pyright_baseline.py tests/test_eval_harness.py tests/test_stack_doc.py \
	tests/test_package_layout.py tests/test_settings_only.py tests/test_ingest_doc.py \
	tests/test_onboarding_doc.py tests/test_postman.py tests/test_ports.py \
	tests/test_query_plans.py \
	tests/test_seed_coverage.py tests/test_analysis_cost.py tests/test_worker_parallel.py

.PHONY: help explain explain-check ports-check bench-ingest bench-analysis stack-check server-group-check verify ingest-every llm up down logs seed backup restore demo test lint fmt fmt-check typecheck pyright-baseline pyright-baseline-check selfcheck openapi-check openapi-write postman postman-check audit sbom lock-upgrade restore-drill loadtest warm ci web-ci e2e e2e-live facts facts-check ruff-baseline ruff-baseline-check eval-gate eval-live changelog review

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

ports-check: ## Fail before `up` if compose publishes a port another stack owns
	$(PY) python -m scripts.check_ports

up: ports-check ## Start the stack (postgres + api) and wait for health
	$(COMPOSE) up -d --build
	@echo "API → http://localhost:8010   docs → http://localhost:8010/docs"

down: ## Stop the stack (keep volumes)
	$(COMPOSE) down

logs: ## Tail api + postgres logs
	$(COMPOSE) logs -f api postgres

seed: ## Load the curated demo dataset into the compose stack
	$(COMPOSE) exec -T api python -m server.seed

backup: ## Dump the database to backups/ (keeps the newest 14)
	$(PY) python scripts/db_backup.py backup

restore: ## Restore a dump: make restore FILE=backups/worldfin-....dump
	$(PY) python scripts/db_backup.py restore $(FILE)

ingest-every: ## Ingest interval in hours: make ingest-every HOURS=1 (demos, keeps the API warm) or HOURS=24
	cd ops/ingest-cron && npx --yes wrangler deploy --var INGEST_EVERY_HOURS:$(HOURS)

llm: ## Switch production LLM: make llm MODEL=... URL=... KEY=... FALLBACK=... (any subset)
	$(PY) python scripts/llm.py $(if $(MODEL),--model "$(MODEL)") $(if $(URL),--url "$(URL)") $(if $(KEY),--key "$(KEY)") $(if $(FALLBACK),--fallback "$(FALLBACK)")

demo: up seed ## Bring up the stack, then seed it — a populated dashboard in one command
	@echo "demo ready → web http://localhost:8080  ·  api http://localhost:8010/docs"
	@echo "walkthrough: docs/DEMO.md"

test: ## Run the test suite (pytest)
	$(PY) pytest -q

lint: ## Lint the whole tree (new debt fails; frozen debt is in ruff-baseline.toml)
	$(PY) ruff check $(NEW_DIRS)
	$(PY) ruff check .

fmt: ## Auto-format new FinScrape code
	$(PY) ruff format $(NEW_DIRS)

fmt-check: ## Check formatting of new FinScrape code (CI gate)
	$(PY) ruff format --check $(NEW_DIRS)

typecheck: ## Type-check the app (pyright: whole tree; ty: server + worker)
	$(PY) pyright
	$(PY) ty check server worker

pyright-baseline: ## Regenerate docs/PYRIGHT-BASELINE.md + pyright-baseline.json
	$(PY) python -m scripts.pyright_baseline

pyright-baseline-check: ## Fail when the type debt grew or the baseline is stale
	$(PY) python -m scripts.pyright_baseline --check

bench-ingest: ## Time the CPU half of an ingest cycle, sequential vs threads (docs/PERF.md)
	$(PY) python -m scripts.bench_ingest --articles $(or $(ARTICLES),6) --workers $(or $(WORKERS),4)

explain: ## Publish EXPLAIN plans for the hot reads to docs/QUERIES.md
	$(PY) python -m scripts.explain --write

explain-check: ## Fail when a filtered feed read no longer uses an index
	$(PY) python -m scripts.explain --check

bench-analysis: ## Time a 6-article analysis cycle sequential vs the bounded pool
	$(PY) python -m scripts.bench_analysis --articles $(or $(ARTICLES),6) --latency $(or $(LATENCY),0.5) --workers $(or $(WORKERS),6)

stack-check: ## Fail when docs/STACK.md disagrees with a pin in the tree
	$(PY) pytest -q tests/test_stack_doc.py tests/test_package_layout.py tests/test_settings_only.py \
		tests/test_ingest_doc.py tests/test_onboarding_doc.py tests/test_ports.py \
		tests/test_query_plans.py tests/test_seed_coverage.py tests/test_analysis_cost.py \
		tests/test_worker_parallel.py

server-group-check: ## Prove the `server` dependency group alone runs the API and worker
	# A scratch environment, so the dev group cannot hide a missing server dependency.
	# `-p 3.14.8` on purpose: on a machine that also has 3.14t, plain `3.14` picks the
	# free-threaded build and two core dependencies have no cp314t wheel there.
	UV_PROJECT_ENVIRONMENT=$(CURDIR)/.venv-server-group \
		uv sync --locked -p 3.14.8 --no-default-groups --group server
	UV_PROJECT_ENVIRONMENT=$(CURDIR)/.venv-server-group \
		$(PY) --no-sync python -c "import server.app, worker.main, finscrape.scrapers; print('server group self-sufficient')"
	@rm -rf .venv-server-group

verify: lint fmt-check typecheck pyright-baseline-check selfcheck openapi-check postman-check test web-ci facts-check ruff-baseline-check eval-gate ## Pre-push gate: `make ci` minus the browser E2E
	@echo "verify: all non-browser gates green"

selfcheck: ## Docker-free Phase 0 checks (settings/schemas/migration SQL/schema drift)
	$(PY) python -m tests.server.selfcheck

openapi-check: ## Fail on a removed path, field, or tightened bound in the API contract
	$(PY) python -m scripts.openapi_snapshot --check

openapi-write: ## Accept an intended contract change into tests/snapshots/openapi.json
	$(PY) python -m scripts.openapi_snapshot --write

postman: ## Regenerate docs/postman.json from the live OpenAPI contract
	$(PY) python -m scripts.postman --write docs/postman.json

postman-check: ## Fail when docs/postman.json no longer matches the contract
	$(PY) python -m scripts.postman --check docs/postman.json

audit: ## Known vulnerabilities in the lock file + web deps (allowlist needs an expiry)
	$(PY) python -m scripts.audit --strict

sbom: ## Write dist/sbom.cdx.json from uv.lock
	$(PY) python -m scripts.sbom --check

lock-upgrade: ## Bump every lock entry (Dependabot does this weekly; this is the local equivalent)
	uv lock --upgrade && uv sync --locked -p 3.14 --group server --group dev

changelog: ## Regenerate CHANGELOG.md from the tagged commit ranges
	$(PY) python ops/release/changelog.py --write
	$(PY) python ops/release/changelog.py --check

review: ## Regenerate the quarterly review block and fail when it is overdue
	$(PY) python ops/review/review.py --write
	$(PY) python ops/review/review.py --check

restore-drill: ## Dump the test DB, restore it, verify row counts + /api/stats, time it
	$(PY) python -m scripts.restore_drill --record

warm: ## Time a cold start (local spawn by default, or URL= to wake a deployment)
	$(PY) python -m scripts.warm $(if $(URL),--base-url $(URL),--spawn) --budget $(or $(BUDGET),120)

loadtest: ## Open-loop read load against a running API (default 50 rps, 10 s)
	$(PY) python -m scripts.loadtest --base-url $(or $(URL),http://127.0.0.1:8010) --rps $(or $(RPS),50) --seconds $(or $(SECONDS),10)

web-ci: ## Web gates: typecheck + Vitest + build + gzip size budget
	cd web && npm ci && npm run typecheck && npm run test && npm run build && npm run budget

e2e: ## Playwright E2E against the built SPA (REST + WS mocked)
	cd web && npm ci && npx playwright install chromium && npx playwright test

e2e-live: ## Playwright against the real API + seeded Postgres (needs WORLDFIN_TEST_DATABASE_URL)
	cd web && npm run e2e:live

facts: ## Regenerate the measured blocks in README.md and docs/ARCHITECTURE.md
	$(PY) python -m scripts.repo_facts --write

facts-check: ## Fail when a doc quotes a count the tree no longer produces
	$(PY) python -m scripts.repo_facts --check

ruff-baseline: ## Regenerate docs/RUFF-BASELINE.md + ruff-baseline.toml, then the doc facts
	$(PY) python -m scripts.ruff_baseline
	$(PY) python -m scripts.repo_facts --write

ruff-baseline-check: ## Fail when docs/RUFF-BASELINE.md no longer matches the tree
	$(PY) python -m scripts.ruff_baseline --check

ci: lint fmt-check typecheck pyright-baseline-check selfcheck openapi-check postman-check test web-ci e2e facts-check ruff-baseline-check eval-gate ## Reproduce the CI pipeline locally

eval-gate: ## Score the frozen gold set offline and refuse a >5 point sector drop
	$(PY) python -m scripts.eval_model --replay tests/gold/recordings/keyword-baseline.jsonl --gate

eval-live: ## Score the configured model against the gold set and append the run to docs/EVAL.md
	$(PY) python -m scripts.eval_model --model $(MODEL) --prompt $(or $(PROMPT),v1) --append-docs
