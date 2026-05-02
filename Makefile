# Parry Makefile — convenience targets for dev and prod operations.
#
# Run `make` (no args) to see the full list.

DEV_COMPOSE  := docker-compose.yml
PROD_COMPOSE := docker-compose.prod.yml

.DEFAULT_GOAL := help

# ── Help ───────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help message
	@awk 'BEGIN {FS = ":.*?## "; printf "\nParry — common targets\n\nUsage:\n  make \033[36m<target>\033[0m\n\n"} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2} /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)}' $(MAKEFILE_LIST)

##@ Development

.PHONY: dev
dev: ## Start the dev stack (db, redis, backend with reload, worker, dashboard)
	docker compose -f $(DEV_COMPOSE) up -d
	@echo "▸ Backend:   http://localhost:8000"
	@echo "▸ API docs:  http://localhost:8000/docs"
	@echo "▸ Dashboard: http://localhost:5173"

.PHONY: dev-down
dev-down: ## Stop the dev stack (data preserved)
	docker compose -f $(DEV_COMPOSE) down

.PHONY: dev-clean
dev-clean: ## Stop the dev stack AND wipe all volumes (destructive)
	docker compose -f $(DEV_COMPOSE) down -v

.PHONY: demo
demo: ## One-command demo bootstrap: start stack, migrate, seed demo org, print API key
	docker compose -f $(DEV_COMPOSE) up -d --wait
	docker compose -f $(DEV_COMPOSE) exec -T backend uv run alembic upgrade head
	docker compose -f $(DEV_COMPOSE) exec -T backend uv run python scripts/seed.py --reset

.PHONY: seed
seed: ## Reseed the demo org against an already-running stack (wipes existing demo data)
	docker compose -f $(DEV_COMPOSE) exec -T backend uv run python scripts/seed.py --reset

.PHONY: logs
logs: ## Tail logs from all dev services
	docker compose -f $(DEV_COMPOSE) logs -f

.PHONY: logs-backend
logs-backend: ## Tail backend logs only
	docker compose -f $(DEV_COMPOSE) logs -f backend

.PHONY: logs-worker
logs-worker: ## Tail celery worker logs only
	docker compose -f $(DEV_COMPOSE) logs -f worker

##@ Database

.PHONY: migrate
migrate: ## Apply pending alembic migrations to the dev DB
	docker compose -f $(DEV_COMPOSE) exec backend uv run alembic upgrade head

.PHONY: migration
migration: ## Generate a new migration. Usage: make migration name="add foo"
	@if [ -z "$(name)" ]; then echo "Usage: make migration name=\"add foo\""; exit 1; fi
	docker compose -f $(DEV_COMPOSE) exec backend uv run alembic revision --autogenerate -m "$(name)"

.PHONY: psql
psql: ## Open a psql shell into the dev database
	docker compose -f $(DEV_COMPOSE) exec db psql -U parry parry

.PHONY: redis-cli
redis-cli: ## Open a redis-cli into the dev redis
	docker compose -f $(DEV_COMPOSE) exec redis redis-cli

##@ Tests & lint

.PHONY: test
test: test-backend test-sdk test-dashboard ## Run all tests (backend + sdk + dashboard)

.PHONY: test-backend
test-backend: ## Run backend tests
	cd backend && uv run pytest -q

.PHONY: test-sdk
test-sdk: ## Run SDK tests
	cd sdk && uv run pytest -q

.PHONY: test-dashboard
test-dashboard: ## Run dashboard tests (vitest)
	cd dashboard && npx vitest --run

.PHONY: lint
lint: lint-backend lint-sdk lint-dashboard ## Lint everything

.PHONY: lint-backend
lint-backend: ## Lint backend (ruff)
	cd backend && uv run ruff check app/ tests/

.PHONY: lint-sdk
lint-sdk: ## Lint SDK (ruff)
	cd sdk && uv run ruff check parry/

.PHONY: lint-dashboard
lint-dashboard: ## Lint dashboard (eslint)
	cd dashboard && npm run lint

.PHONY: format
format: ## Auto-format backend and SDK with ruff
	cd backend && uv run ruff format app/ tests/
	cd sdk && uv run ruff format parry/ tests/

##@ Production (run these on the droplet)

.PHONY: deploy
deploy: ## Pull main and roll services. Run this on the prod host.
	./scripts/deploy.sh

.PHONY: deploy-force
deploy-force: ## Force a clean rebuild from scratch on the prod host
	./scripts/deploy.sh --force

.PHONY: prod-up
prod-up: ## Start the prod stack (caddy, backend, worker, dashboard, db, redis)
	docker compose -f $(PROD_COMPOSE) up -d

.PHONY: prod-down
prod-down: ## Stop the prod stack (data preserved)
	docker compose -f $(PROD_COMPOSE) down

.PHONY: prod-logs
prod-logs: ## Tail logs from all prod services
	docker compose -f $(PROD_COMPOSE) logs -f

.PHONY: prod-status
prod-status: ## Show prod service health
	docker compose -f $(PROD_COMPOSE) ps

.PHONY: prod-psql
prod-psql: ## psql shell into the prod database
	docker compose -f $(PROD_COMPOSE) exec db psql -U parry parry

.PHONY: prod-shell
prod-shell: ## Bash shell inside the running prod backend container
	docker compose -f $(PROD_COMPOSE) exec backend bash

.PHONY: prod-migrate
prod-migrate: ## Manually run alembic migrations on prod (normally automatic)
	docker compose -f $(PROD_COMPOSE) exec backend uv run alembic upgrade head

##@ Backups

.PHONY: backup
backup: ## Dump the prod database to ./backups/parry_<date>.dump
	@mkdir -p backups
	@FILE=backups/parry_$$(date +%Y%m%d_%H%M%S).dump; \
	docker compose -f $(PROD_COMPOSE) exec -T db pg_dump -U parry -Fc parry > $$FILE && \
	echo "▸ Backup written to $$FILE ($$(du -h $$FILE | cut -f1))"

.PHONY: restore
restore: ## Restore a backup. Usage: make restore file=backups/parry_20260407.dump
	@if [ -z "$(file)" ]; then echo "Usage: make restore file=backups/parry_<date>.dump"; exit 1; fi
	@if [ ! -f "$(file)" ]; then echo "ERROR: $(file) not found"; exit 1; fi
	@echo "▸ Restoring $(file) — this will OVERWRITE the current database."
	@read -p "Continue? [y/N] " ans; [ "$$ans" = "y" ] || exit 1
	docker compose -f $(PROD_COMPOSE) exec -T db pg_restore -U parry -d parry --clean < $(file)
	@echo "▸ Restore complete"

##@ Health checks

.PHONY: health
health: ## Hit the dev /health endpoint
	@curl -sf http://localhost:8000/health | python3 -m json.tool || echo "Backend not reachable"

.PHONY: prod-health
prod-health: ## Hit the prod /health endpoint via Caddy
	@DOMAIN=$$(grep ^DOMAIN= .env 2>/dev/null | cut -d= -f2); \
	if [ -z "$$DOMAIN" ]; then echo "DOMAIN not set in .env"; exit 1; fi; \
	curl -sf https://$$DOMAIN/health | python3 -m json.tool || echo "Prod backend not reachable"
