#!/usr/bin/env bash
# Nova Platform setup script (non-interactive backend)
# Called by ./setup wizard or directly. Reads .env for configuration.
# Reads models.yaml to determine which Ollama models to pull on startup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODELS_YAML="${PROJECT_ROOT}/models.yaml"

echo "═══════════════════════════════════════════════════════"
echo "  Nova AI Platform — Setup"
echo "═══════════════════════════════════════════════════════"

# ── Copy .env if missing ──────────────────────────────────────────────────────
if [ ! -f "${PROJECT_ROOT}/.env" ]; then
  if [ -f "${PROJECT_ROOT}/.env.example" ]; then
    cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
    echo "✓ Created .env from .env.example"
    echo "  → Run ./setup to configure interactively, or edit .env manually"
  else
    echo "✗ No .env or .env.example found. Run ./setup to generate one."
    exit 1
  fi
fi

# ── Source .env for config choices ────────────────────────────────────────────
set -a
# shellcheck disable=SC1091
. "${PROJECT_ROOT}/.env"
set +a

# ── Generate credential master key if not set ─────────────────────────────────
if grep -q "^CREDENTIAL_MASTER_KEY=$" "${PROJECT_ROOT}/.env" 2>/dev/null; then
  CREDENTIAL_MASTER_KEY=$(openssl rand -hex 32)
  sed -i "s/^CREDENTIAL_MASTER_KEY=$/CREDENTIAL_MASTER_KEY=${CREDENTIAL_MASTER_KEY}/" "${PROJECT_ROOT}/.env"
  echo "  Generated CREDENTIAL_MASTER_KEY"
fi

# ── Generate bridge service secret if not set ──────────────────────────────────
if grep -q "^BRIDGE_SERVICE_SECRET=$" "${PROJECT_ROOT}/.env" 2>/dev/null; then
  BRIDGE_SERVICE_SECRET=$(openssl rand -hex 32)
  sed -i "s/^BRIDGE_SERVICE_SECRET=$/BRIDGE_SERVICE_SECRET=${BRIDGE_SERVICE_SECRET}/" "${PROJECT_ROOT}/.env"
  echo "  Generated BRIDGE_SERVICE_SECRET"
fi

# ── Create workspace directory ────────────────────────────────────────────────
# Resolve ~ manually since Docker Compose doesn't expand it in all contexts
NOVA_WORKSPACE="${NOVA_WORKSPACE:-${HOME}/.nova/workspace}"
NOVA_WORKSPACE="${NOVA_WORKSPACE/#\~/$HOME}"
if [ ! -d "${NOVA_WORKSPACE}" ]; then
  mkdir -p "${NOVA_WORKSPACE}"
  echo "✓ Created workspace at ${NOVA_WORKSPACE}"
else
  echo "✓ Workspace: ${NOVA_WORKSPACE}"
fi
export NOVA_WORKSPACE

# ── Create persistent data directories ──────────────────────────────────
POSTGRES_DATA_DIR="${POSTGRES_DATA_DIR:-${PROJECT_ROOT}/data/postgres}"
REDIS_DATA_DIR="${REDIS_DATA_DIR:-${PROJECT_ROOT}/data/redis}"
for dir in "${POSTGRES_DATA_DIR}" "${REDIS_DATA_DIR}"; do
  if [ ! -d "${dir}" ]; then
    mkdir -p "${dir}"
    echo "✓ Created data directory: ${dir}"
  fi
done

# ── Resolve magic Ollama URL values ──────────────────────────────────────────
if [ "${OLLAMA_BASE_URL:-}" = "auto" ] || [ "${OLLAMA_BASE_URL:-}" = "host" ]; then
  RESOLVED_URL="$(bash "${SCRIPT_DIR}/resolve-ollama-url.sh")"
  echo "  Ollama URL: ${OLLAMA_BASE_URL} -> ${RESOLVED_URL}"
  export OLLAMA_BASE_URL="${RESOLVED_URL}"
fi

# ── Determine which local inference backends are active ──────────────────────
USE_LOCAL_OLLAMA=false
USE_LOCAL_VLLM=false
USE_LOCAL_SGLANG=false
case "${COMPOSE_PROFILES:-}" in
  *local-ollama*)  USE_LOCAL_OLLAMA=true ;;
esac
case "${COMPOSE_PROFILES:-}" in
  *local-vllm*)    USE_LOCAL_VLLM=true ;;
esac
case "${COMPOSE_PROFILES:-}" in
  *local-sglang*)  USE_LOCAL_SGLANG=true ;;
esac

# Skip Ollama entirely for cloud-only mode
if [ "${LLM_ROUTING_STRATEGY:-local-first}" = "cloud-only" ]; then
  USE_LOCAL_OLLAMA=false
fi

NEEDS_LOCAL_INFERENCE=false
if [ "${USE_LOCAL_OLLAMA}" = "true" ] || [ "${USE_LOCAL_VLLM}" = "true" ] || [ "${USE_LOCAL_SGLANG}" = "true" ]; then
  NEEDS_LOCAL_INFERENCE=true
fi

# ── Detect GPU and pick compose files ────────────────────────────────────────
COMPOSE_FILES="-f docker-compose.yml"

if [ "${NOVA_GPU:-auto}" = "nvidia" ] || ([ "${NOVA_GPU:-auto}" = "auto" ] && command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null); then
  COMPOSE_FILES="${COMPOSE_FILES} -f docker-compose.gpu.yml"
  echo "✓ NVIDIA GPU detected — using docker-compose.gpu.yml overlay"
  echo "  (set NOVA_GPU=cpu in .env to disable GPU mode)"
elif [ "${NOVA_GPU:-auto}" = "rocm" ]; then
  COMPOSE_FILES="${COMPOSE_FILES} -f docker-compose.rocm.yml"
  echo "✓ AMD ROCm GPU mode enabled"
else
  if [ "${USE_LOCAL_VLLM}" = "true" ] || [ "${USE_LOCAL_SGLANG}" = "true" ]; then
    echo "⚠ No GPU detected but vLLM/SGLang requested — these require a GPU"
    echo "  Consider using Ollama (CPU-capable) or cloud providers instead"
  fi
  echo "  Running in CPU mode (Apple Silicon uses Metal automatically)"
fi

if [ "${NEEDS_LOCAL_INFERENCE}" = "false" ]; then
  if [ "${LLM_ROUTING_STRATEGY:-local-first}" = "cloud-only" ]; then
    echo "  Cloud-only mode — no local inference backend"
  else
    echo "  Using remote inference at ${OLLAMA_BASE_URL:-<not set>}"
  fi
fi

# ── Hardware detection ─────────────────────────────────────────────────────────
echo ""
echo "Detecting hardware..."
"${SCRIPT_DIR}/detect_hardware.sh" "${PROJECT_ROOT}/data/hardware.json"
echo ""

# ── Parse models to pull from models.yaml ────────────────────────────────────
if [ "${USE_LOCAL_OLLAMA}" = "true" ]; then
  if [ ! -f "${MODELS_YAML}" ]; then
    echo "⚠ models.yaml not found at ${MODELS_YAML} — using defaults"
    MODELS_TO_PULL=("nomic-embed-text" "qwen2.5:1.5b" "llama3.2")
  else
    _TMPPY=$(mktemp /tmp/nova_parse_XXXXXX.py)
    cat > "${_TMPPY}" <<'PYEOF'
import sys, re
models_file = sys.argv[1] if len(sys.argv) > 1 else "models.yaml"
try:
    import yaml
    with open(models_file) as f:
        data = yaml.safe_load(f)
    for m in data.get("ollama", {}).get("pull_on_startup", []):
        print(m["name"])
except ImportError:
    with open(models_file) as f:
        content = f.read()
    for match in re.finditer(r'^    - name:\s*(\S+)', content, re.MULTILINE):
        print(match.group(1))
PYEOF

    MODELS_TO_PULL=()
    while IFS= read -r model_name; do
      [ -n "${model_name}" ] && MODELS_TO_PULL+=("${model_name}")
    done < <(python3 "${_TMPPY}" "${MODELS_YAML}")
    rm -f "${_TMPPY}"
  fi

  echo ""
  echo "→ Models to pull: ${MODELS_TO_PULL[*]:-none}"
else
  MODELS_TO_PULL=()
fi

# ── Start infrastructure services ────────────────────────────────────────────
echo ""
echo "→ Starting infrastructure (postgres, redis)..."
cd "${PROJECT_ROOT}"
docker compose ${COMPOSE_FILES} up -d postgres redis

# ── Start Ollama if configured ───────────────────────────────────────────────
if [ "${USE_LOCAL_OLLAMA}" = "true" ]; then
  echo ""
  echo "→ Starting Ollama..."
  docker compose ${COMPOSE_FILES} up -d ollama

  echo "→ Waiting for Ollama to be healthy (this can take 30-60 s on first run)..."
  docker compose ${COMPOSE_FILES} up -d --wait ollama 2>/dev/null || {
    echo "  (falling back to port polling — upgrade Docker Compose for faster startup)"
    for i in $(seq 1 60); do
      if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
        break
      fi
      sleep 2
      echo "  Still waiting for Ollama... (${i}/60)"
    done
    curl -sf http://localhost:11434/api/tags > /dev/null 2>&1 || {
      echo "✗ Ollama did not become ready in 120 s. Check: docker compose logs ollama"
      exit 1
    }
  }
  echo "✓ Ollama is ready"

  # Pull models
  for model in "${MODELS_TO_PULL[@]}"; do
    echo ""
    echo "→ Pulling ${model}..."
    docker compose ${COMPOSE_FILES} exec -T ollama ollama pull "${model}" \
      || echo "  ⚠ Failed to pull ${model} (may already exist — continuing)"
  done
fi

# ── Start vLLM / SGLang if configured ───────────────────────────────────────
if [ "${USE_LOCAL_VLLM}" = "true" ]; then
  echo ""
  echo "→ Starting vLLM (model: ${VLLM_MODEL:-Qwen/Qwen2.5-1.5B-Instruct})..."
  echo "  First start downloads the model from HuggingFace — this may take several minutes."
  docker compose ${COMPOSE_FILES} --profile local-vllm up -d nova-vllm
fi

if [ "${USE_LOCAL_SGLANG}" = "true" ]; then
  echo ""
  echo "→ Starting SGLang (model: ${SGLANG_MODEL:-Qwen/Qwen2.5-3B-Instruct})..."
  echo "  First start downloads the model from HuggingFace — this may take several minutes."
  docker compose ${COMPOSE_FILES} --profile local-sglang up -d nova-sglang
fi

# ── Start all Nova platform services ─────────────────────────────────────────
echo ""
echo "→ Starting all Nova services..."
docker compose ${COMPOSE_FILES} up -d

echo ""
echo "→ Waiting for all services to be healthy (up to 2 minutes)..."
docker compose ${COMPOSE_FILES} up -d --wait 2>/dev/null || sleep 20

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Nova is running!"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  Dashboard:      http://localhost:3001"
echo "  Chat UI:        http://localhost:8080"
echo ""
echo "  API docs:       http://localhost:8000/docs  (orchestrator)"
echo "                  http://localhost:8001/docs  (llm-gateway)"
echo "                  http://localhost:8002/docs  (memory-service)"
echo ""
echo "  Logs: docker compose logs -f"
echo "  Stop: docker compose down"
echo ""
echo "  To reconfigure: ./setup"
echo "  To add/remove models: edit models.yaml, then re-run ./scripts/setup.sh"
