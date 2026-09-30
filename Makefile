# WorldFin developer commands. See PLAN.md.
# Python tasks run via uv pinned to 3.13 (spacy has no 3.14 wheel yet) with the
# server + dev groups so FastAPI/asyncpg/ruff are present.
.DEFAULT_GOAL := help
PY := uv run -p 3.13 --group server --group dev
COMPOSE := docker compose

# New (WorldFin) code only — pre-existing finscrape source isn't ruff-format clean,
# so formatting is scoped to avoid a noisy whole-repo reformat.
NEW_DIRS := server worker finscrape/scrapers/world finscrape/ingestors \
	finscrape/scenarios.py \
	tests/server tests/test_world_phase2.py tests/test_worker_phase3.py \
	tests/test_correlate_phase4.py tests/test_scenarios.py tests/test_no_multi_model.py tests/live_e2e.py

.PHONY: help up down logs seed backup restore demo test lint fmt fmt-check typecheck selfcheck ci web-ci e2e e2e-live

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Start the stack (postgres + api) and wait for health
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

demo: up seed ## Bring up the stack, then seed it — a populated dashboard in one command
	@echo "demo ready → web http://localhost:8080  ·  api http://localhost:8010/docs"
	@echo "walkthrough: docs/DEMO.md"

test: ## Run the test suite (pytest)
	$(PY) pytest -q

lint: ## Lint new WorldFin code with ruff (pre-existing finscrape debt is out of scope)
	$(PY) ruff check $(NEW_DIRS)

fmt: ## Auto-format new WorldFin code
	$(PY) ruff format $(NEW_DIRS)

fmt-check: ## Check formatting of new WorldFin code (CI gate)
	$(PY) ruff format --check $(NEW_DIRS)

typecheck: ## Type-check the WorldFin backend (pyright, scoped to server/ + worker/)
	$(PY) pyright

selfcheck: ## Docker-free Phase 0 checks (settings/schemas/migration SQL)
	$(PY) python -m tests.server.selfcheck

web-ci: ## Web gates: typecheck + Vitest + build
	cd web && npm ci && npm run typecheck && npm run test && npm run build

e2e: ## Playwright E2E against the built SPA (REST + WS mocked)
	cd web && npm ci && npx playwright install chromium && npx playwright test

e2e-live: ## Playwright against the real API + seeded Postgres (needs WORLDFIN_TEST_DATABASE_URL)
	cd web && npm run e2e:live

ci: lint fmt-check typecheck selfcheck test web-ci e2e ## Reproduce the CI pipeline locally
