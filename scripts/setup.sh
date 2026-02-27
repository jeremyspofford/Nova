#!/usr/bin/env bash
# Nova Platform setup script
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
  cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
  echo "✓ Created .env from .env.example"
  echo "  → Edit .env to add your API keys / auth tokens"
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
  echo "  Running in CPU mode (Apple Silicon uses Metal automatically)"
  echo "  (set NOVA_GPU=nvidia in .env for NVIDIA GPU, or NOVA_GPU=rocm for AMD)"
fi

# ── Parse models to pull from models.yaml ────────────────────────────────────
if [ ! -f "${MODELS_YAML}" ]; then
  echo "⚠ models.yaml not found at ${MODELS_YAML} — using defaults"
  MODELS_TO_PULL=("nomic-embed-text" "llama3.2")
else
  # Use Python (guaranteed present in any environment) to parse the YAML.
  # Write the parser to a temp file first — combining <<'EOF' inside <(...)
  # confuses bash's parser on macOS bash 3.2 and some bash 5.x versions.
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
    # Fallback: simple regex parse without PyYAML
    with open(models_file) as f:
        content = f.read()
    # Find lines like "    - name: llama3.2" that aren't commented out
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

# ── Start infrastructure services and wait for healthy status ─────────────────
echo ""
echo "→ Starting infrastructure (postgres, redis, ollama)..."
cd "${PROJECT_ROOT}"
docker compose ${COMPOSE_FILES} up -d postgres redis ollama

# --wait makes docker compose block until ALL listed services are healthy.
# Much more reliable than manual polling: respects each service's own healthcheck.
echo ""
echo "→ Waiting for Ollama to be healthy (this can take 30–60 s on first run)..."
docker compose ${COMPOSE_FILES} up -d --wait ollama 2>/dev/null || {
  # Fallback for older docker-compose without --wait flag
  echo "  (falling back to port polling — upgrade Docker Compose for faster startup)"
  for i in $(seq 1 60); do
    if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
      break
    fi
    sleep 2
    echo "  Still waiting for Ollama... (${i}/60)"
  done
  # Final check
  curl -sf http://localhost:11434/api/tags > /dev/null 2>&1 || {
    echo "✗ Ollama did not become ready in 120 s. Check: docker compose logs ollama"
    exit 1
  }
}
echo "✓ Ollama is ready"

# ── Pull models listed in models.yaml ────────────────────────────────────────
for model in "${MODELS_TO_PULL[@]}"; do
  echo ""
  echo "→ Pulling ${model}..."
  docker compose ${COMPOSE_FILES} exec -T ollama ollama pull "${model}" \
    || echo "  ⚠ Failed to pull ${model} (may already exist — continuing)"
done

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
echo "  Chat UI:        http://localhost:8080"
echo "  Chat API docs:  http://localhost:8080/docs"
echo "  Orchestrator:   http://localhost:8000/docs"
echo "  Memory Service: http://localhost:8002/docs"
echo "  LLM Gateway:    http://localhost:8001/docs"
echo ""
echo "  WebSocket:      ws://localhost:8080/ws/chat"
echo ""
echo "  Logs: docker compose logs -f"
echo "  Stop: docker compose down"
echo ""
echo "  To add/remove models: edit models.yaml, then re-run ./scripts/setup.sh"
