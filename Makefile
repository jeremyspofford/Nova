.PHONY: help setup up dev build down logs ps watch migrate backup restore website test test-quick benchmark-quality prune prune-all

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

# ── Ollama URL auto-detection ────────────────────────────────────────────
OLLAMA_BASE_URL ?=
ifneq ($(filter auto host,$(OLLAMA_BASE_URL)),)
  RESOLVED_OLLAMA_URL := $(shell ./scripts/resolve-ollama-url.sh)
  export OLLAMA_BASE_URL := $(RESOLVED_OLLAMA_URL)
endif

EDITOR_PROFILE := $(if $(filter vscode,$(EDITOR_FLAVOR)),--profile editor-vscode,$(if $(filter neovim,$(EDITOR_FLAVOR)),--profile editor-neovim,))
COMPOSE      = docker compose -f docker-compose.yml $(GPU_OVERLAY) --profile voice $(EDITOR_PROFILE)
ALL_PROFILES = --profile voice --profile website --profile bridges --profile knowledge \
               --profile local-ollama --profile local-vllm --profile local-sglang \
               --profile cloudflare-tunnel --profile tailscale \
               --profile editor-vscode --profile editor-neovim

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

down: ## Stop and remove all containers (all profiles + orphans)
	docker compose -f docker-compose.yml $(GPU_OVERLAY) $(ALL_PROFILES) down --remove-orphans

# ── Develop ──────────────────────────────────────────────────────────────────
dev: ## Start all services detached + Vite dashboard with hot-reload  [1-line dev]
	$(COMPOSE) --profile website up -d --remove-orphans
	cd $(DASHBOARD) && npm run dev

watch: ## Sync Python source into running containers for backend hot-reload
	$(COMPOSE) watch

website: ## Build and start the Nova website at http://localhost:4000
	$(COMPOSE) --profile website up -d --build website

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
# ── Testing ──────────────────────────────────────────────────────────────────
test: ## Run integration tests against running services
	@cd tests && uv run --with pytest --with pytest-asyncio --with httpx --with websockets --with python-dotenv --with redis --with asyncpg --with requests \
	  pytest -v --tb=short

test-quick: ## Smoke test (health endpoints only)
	@cd tests && uv run --with pytest --with pytest-asyncio --with httpx --with websockets --with python-dotenv --with redis --with asyncpg --with requests \
	  pytest -v --tb=short -k "health"

benchmark-quality: ## Run AI quality benchmark suite
	python -m benchmarks.quality.runner

# ── Backup / Restore ─────────────────────────────────────────────────────────
backup: ## Create a database backup (emergency — normally use the Recovery UI)
	@./scripts/backup.sh

restore: ## List or restore backups (emergency — normally use the Recovery UI)
	@./scripts/restore.sh $(F)

# ── Cleanup ────────────────────────────────────────────────────────────────
prune: ## Remove stopped containers, dangling images, build cache (preserves ALL volumes)
	docker system prune -f
	@echo "\n  Volumes untouched. Use 'make prune-all' to also clean model caches."

prune-all: ## Backup DB, then prune everything including model cache volumes
	@echo "This will remove Ollama/vLLM/SGLang model caches (re-downloadable)."
	@echo "Postgres and Redis data are safe (bind-mounted to ./data/)."
	@read -p "Continue? [y/N] " yn; [ "$$yn" = "y" ] || exit 1
	@./scripts/backup.sh
	docker system prune -f
	@for v in ollama-data nova-vllm-cache nova-sglang-cache tailscale-state; do \
	  docker volume rm "nova_$$v" 2>/dev/null && echo "  Removed $$v" || true; \
	done
