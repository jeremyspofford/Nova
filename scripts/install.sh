#!/usr/bin/env bash
# Nova Platform setup script (non-interactive backend)
# Called by ./install wizard or directly. Reads .env for configuration.
# Reads models.yaml to determine which Ollama models to pull on startup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODELS_YAML="${PROJECT_ROOT}/models.yaml"
# ENV_FILE is overridable so tests can point at an isolated .env without
# touching the user's real configuration.
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/.env}"

# ── Argument parsing ─────────────────────────────────────────────────────────
# --derive-mode-only: tests/test_inference_modes.py uses this fast path to
# verify mode→env derivation without pulling models or hitting Docker.
DERIVE_MODE_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --derive-mode-only) DERIVE_MODE_ONLY=true ;;
  esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────
# Idempotent: replace the line setting KEY=... in $ENV_FILE, or append it if
# absent. Comments and other lines are preserved. Treats keys atomically (no
# partial-match collisions).
upsert_env() {
  local key="$1"
  local value="$2"
  local file="${ENV_FILE}"
  if [ ! -f "${file}" ]; then
    printf '%s=%s\n' "${key}" "${value}" > "${file}"
    return
  fi
  if grep -q "^${key}=" "${file}" 2>/dev/null; then
    local tmp
    tmp=$(mktemp)
    awk -v k="${key}" -v v="${value}" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' "${file}" > "${tmp}"
    mv "${tmp}" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${file}"
  fi
}

# Add or remove a single token from a comma-separated list in COMPOSE_PROFILES.
# Preserves any other tokens already present (e.g. bridges, knowledge).
compose_profiles_set() {
  local action="$1"   # add | remove
  local token="$2"
  local current=""
  if [ -f "${ENV_FILE}" ]; then
    current=$(grep -m1 '^COMPOSE_PROFILES=' "${ENV_FILE}" 2>/dev/null | cut -d= -f2- || true)
  fi
  local IFS=','
  local -a parts=()
  for p in ${current}; do
    p=$(echo "${p}" | xargs)
    [ -n "${p}" ] && parts+=("${p}")
  done
  local -a out=()
  local found=false
  for p in "${parts[@]}"; do
    if [ "${p}" = "${token}" ]; then
      found=true
      [ "${action}" = "remove" ] && continue
    fi
    out+=("${p}")
  done
  if [ "${action}" = "add" ] && [ "${found}" = false ]; then
    out+=("${token}")
  fi
  upsert_env COMPOSE_PROFILES "$(IFS=,; echo "${out[*]}")"
}

if [ "${DERIVE_MODE_ONLY}" != "true" ]; then
  echo "═══════════════════════════════════════════════════════"
  echo "  Nova AI Platform — Setup"
  echo "═══════════════════════════════════════════════════════"
fi

# ── Copy .env if missing ──────────────────────────────────────────────────────
if [ ! -f "${ENV_FILE}" ]; then
  if [ -f "${PROJECT_ROOT}/.env.example" ]; then
    cp "${PROJECT_ROOT}/.env.example" "${ENV_FILE}"
    echo "✓ Created ${ENV_FILE} from .env.example"
    echo "  → Run ./install to configure interactively, or edit ${ENV_FILE} manually"
  else
    echo "✗ No ${ENV_FILE} or .env.example found. Run ./install to generate one."
    exit 1
  fi
fi

# Capture explicit NOVA_INFERENCE_MODE override BEFORE sourcing ENV_FILE.
# This lets a user (or test) re-run setup.sh with NOVA_INFERENCE_MODE=<new>
# to switch modes without first hand-editing .env.
_NOVA_INFERENCE_MODE_OVERRIDE="${NOVA_INFERENCE_MODE:-}"

# ── Source .env for config choices ────────────────────────────────────────────
set -a
# shellcheck disable=SC1091
. "${ENV_FILE}"
set +a

# Apply override (if any) AFTER sourcing, so an explicit shell-env value wins
# over the persisted .env value.
if [ -n "${_NOVA_INFERENCE_MODE_OVERRIDE}" ]; then
  NOVA_INFERENCE_MODE="${_NOVA_INFERENCE_MODE_OVERRIDE}"
fi

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

# ── Generate Postgres password if not set ──────────────────────────────────────
if grep -q "^POSTGRES_PASSWORD=$" "${PROJECT_ROOT}/.env" 2>/dev/null; then
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  sed -i "s|^POSTGRES_PASSWORD=$|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" "${PROJECT_ROOT}/.env"
  echo "  Generated POSTGRES_PASSWORD"
fi

# ── Rotate admin secret if still the shipped placeholder ───────────────────────
if grep -q '^NOVA_ADMIN_SECRET=nova-admin-secret-change-me$' "${PROJECT_ROOT}/.env" 2>/dev/null; then
  NOVA_ADMIN_SECRET=$(openssl rand -hex 32)
  sed -i "s|^NOVA_ADMIN_SECRET=nova-admin-secret-change-me$|NOVA_ADMIN_SECRET=${NOVA_ADMIN_SECRET}|" "${PROJECT_ROOT}/.env"
  echo "  Generated NOVA_ADMIN_SECRET"
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

# ── Inference mode selection ─────────────────────────────────────────────────
# NOVA_INFERENCE_MODE is the user-facing knob: hybrid | local-only | cloud-only.
# It derives COMPOSE_PROFILES (whether to ship+start bundled Ollama) and
# LLM_ROUTING_STRATEGY (how the gateway picks providers). Settings UI can
# change this later; setup.sh asks once if it's not already set.
if [ -z "${NOVA_INFERENCE_MODE:-}" ] && [ -t 0 ] && [ "${DERIVE_MODE_ONLY}" != "true" ]; then
  echo ""
  echo "Nova can run with local AI, cloud AI, or both."
  echo ""
  echo "  [1] hybrid     — bundle Ollama for local AI, fall back to cloud (recommended)"
  echo "  [2] local-only — bundle Ollama, never use cloud (privacy/offline-friendly)"
  echo "  [3] cloud-only — no bundled Ollama, only use cloud APIs (lighter setup)"
  echo ""
  echo "You can change this anytime in Settings → AI & Models."
  printf "Choice [1/2/3] (default 1): "
  read -r choice
  case "${choice:-1}" in
    2) NOVA_INFERENCE_MODE=local-only ;;
    3) NOVA_INFERENCE_MODE=cloud-only ;;
    *) NOVA_INFERENCE_MODE=hybrid ;;
  esac
elif [ -z "${NOVA_INFERENCE_MODE:-}" ]; then
  NOVA_INFERENCE_MODE=hybrid
fi

case "${NOVA_INFERENCE_MODE}" in
  hybrid|local-only|cloud-only) ;;
  *)
    echo "ERROR: invalid NOVA_INFERENCE_MODE='${NOVA_INFERENCE_MODE}'." >&2
    echo "  Must be one of: hybrid, local-only, cloud-only." >&2
    exit 2
    ;;
esac

case "${NOVA_INFERENCE_MODE}" in
  hybrid)
    compose_profiles_set add local-ollama
    upsert_env LLM_ROUTING_STRATEGY local-first
    USE_LOCAL_OLLAMA=true
    ;;
  local-only)
    compose_profiles_set add local-ollama
    upsert_env LLM_ROUTING_STRATEGY local-only
    USE_LOCAL_OLLAMA=true
    ;;
  cloud-only)
    compose_profiles_set remove local-ollama
    upsert_env LLM_ROUTING_STRATEGY cloud-only
    USE_LOCAL_OLLAMA=false
    ;;
esac
upsert_env NOVA_INFERENCE_MODE "${NOVA_INFERENCE_MODE}"

# Re-source ENV_FILE so subsequent steps see the just-written values.
set -a
# shellcheck disable=SC1091
. "${ENV_FILE}"
set +a

USE_LOCAL_VLLM=false
USE_LOCAL_SGLANG=false
case "${COMPOSE_PROFILES:-}" in
  *local-vllm*)    USE_LOCAL_VLLM=true ;;
esac
case "${COMPOSE_PROFILES:-}" in
  *local-sglang*)  USE_LOCAL_SGLANG=true ;;
esac

if [ "${DERIVE_MODE_ONLY}" != "true" ]; then
  echo "  Inference mode: ${NOVA_INFERENCE_MODE}"
fi

# Test fast-path exit. Comes AFTER all upsert_env calls so the test can
# observe the derived values, but BEFORE Docker/model work below.
if [ "${DERIVE_MODE_ONLY}" = "true" ]; then
  exit 0
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
# Each entry is encoded as "<name>|<required>" so the pull loop can fail-fast
# on a required: true model that doesn't pull. Optional models stay best-effort.
if [ "${USE_LOCAL_OLLAMA}" = "true" ]; then
  if [ ! -f "${MODELS_YAML}" ]; then
    echo "⚠ models.yaml not found at ${MODELS_YAML} — using defaults"
    MODELS_TO_PULL=("nomic-embed-text|true" "qwen2.5:1.5b|true" "llama3.2|false")
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
        print(f"{m['name']}|{'true' if m.get('required', False) else 'false'}")
except ImportError:
    # Fallback hand-rolled parse (no PyYAML available).
    with open(models_file) as f:
        content = f.read()
    # Each entry is a name line optionally followed by a required line.
    for block in re.split(r'(?m)^    - name:', content)[1:]:
        m_name = re.match(r'\s*(\S+)', block)
        if not m_name:
            continue
        name = m_name.group(1)
        m_req = re.search(r'^      required:\s*(\S+)', block, re.MULTILINE)
        required = (m_req.group(1).lower() == 'true') if m_req else False
        print(f"{name}|{'true' if required else 'false'}")
PYEOF

    MODELS_TO_PULL=()
    while IFS= read -r entry; do
      [ -n "${entry}" ] && MODELS_TO_PULL+=("${entry}")
    done < <(python3 "${_TMPPY}" "${MODELS_YAML}")
    rm -f "${_TMPPY}"
  fi

  echo ""
  REQUIRED_NAMES=()
  OPTIONAL_NAMES=()
  for entry in "${MODELS_TO_PULL[@]}"; do
    name="${entry%|*}"; req="${entry##*|}"
    if [ "${req}" = "true" ]; then REQUIRED_NAMES+=("${name}"); else OPTIONAL_NAMES+=("${name}"); fi
  done
  echo "→ Required models: ${REQUIRED_NAMES[*]:-none}"
  echo "→ Optional models: ${OPTIONAL_NAMES[*]:-none}"
else
  MODELS_TO_PULL=()
  echo "  Skipping model pulls (cloud-only mode)."
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

  # Pull models. Required pulls are fail-fast (exit non-zero on failure);
  # optional pulls are best-effort.
  for entry in "${MODELS_TO_PULL[@]}"; do
    model="${entry%|*}"
    required="${entry##*|}"
    echo ""
    echo "→ Pulling ${model} (required=${required})..."
    if ! docker compose ${COMPOSE_FILES} exec -T ollama ollama pull "${model}"; then
      if [ "${required}" = "true" ]; then
        echo "✗ ERROR: required model '${model}' failed to pull. Aborting setup." >&2
        exit 1
      else
        echo "  ⚠ Optional model '${model}' failed to pull — continuing."
      fi
    fi
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
echo "  To reconfigure: ./install"
echo "  To add/remove models: edit models.yaml, then re-run ./scripts/install.sh"
