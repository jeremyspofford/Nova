.PHONY: help setup up dev build down logs ps watch migrate backup restore

DASHBOARD    = dashboard

# ── GPU auto-detection ────────────────────────────────────────────────────────
# Override with NOVA_GPU=cpu|nvidia|rocm in .env or environment
NOVA_GPU     ?= auto
GPU_OVERLAY  :=
ifeq ($(NOVA_GPU),nvidia)
  GPU_OVERLAY = -f docker-compose.gpu.yml
else ifeq ($(NOVA_GPU),rocm)
  GPU_OVERLAY = -f docker-compose.rocm.yml
else ifeq ($(NOVA_GPU),auto)
  GPU_OVERLAY = $(shell command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1 && echo "-f docker-compose.gpu.yml")
endif

COMPOSE      = docker compose -f docker-compose.yml $(GPU_OVERLAY)

# ─────────────────────────────────────────────────────────────────────────────
help: ## Show available commands
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z_-]+:.*?## / \
	  {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Interactive setup wizard (first-time or reconfigure)
	@./setup

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

# ── Backup / Restore ─────────────────────────────────────────────────────────
backup: ## Create a database backup (emergency — normally use the Recovery UI)
	@./scripts/backup.sh

restore: ## List or restore backups (emergency — normally use the Recovery UI)
	@./scripts/restore.sh $(F)
