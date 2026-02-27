.PHONY: help up dev build down logs ps watch migrate

COMPOSE      = docker compose
DASHBOARD    = dashboard

# ─────────────────────────────────────────────────────────────────────────────
help: ## Show available commands
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z_-]+:.*?## / \
	  {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Deploy ───────────────────────────────────────────────────────────────────
up: ## Start all services detached (production / staging)
	$(COMPOSE) up -d

build: ## Rebuild all Docker images (run before up after code changes)
	$(COMPOSE) build

down: ## Stop and remove all containers
	$(COMPOSE) down

# ── Develop ──────────────────────────────────────────────────────────────────
dev: ## Start backend detached + Vite dashboard with hot-reload  [1-line dev]
	$(COMPOSE) up -d
	cd $(DASHBOARD) && npm run dev

watch: ## Sync Python source into running containers for backend hot-reload
	$(COMPOSE) watch

# ── Observe ──────────────────────────────────────────────────────────────────
logs: ## Tail logs for all services
	$(COMPOSE) logs -f

ps: ## Show container status
	$(COMPOSE) ps

# ── Database ─────────────────────────────────────────────────────────────────
migrate: ## Apply pending SQL migrations (runs inside orchestrator container)
	$(COMPOSE) exec orchestrator python -c \
	  "import asyncio; from app.db import init_db; asyncio.run(init_db())"
