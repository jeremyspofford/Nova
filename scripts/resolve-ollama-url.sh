#!/usr/bin/env bash
# Resolve magic OLLAMA_BASE_URL values to concrete URLs.
#
# Magic values:
#   host  — Ollama runs on the host machine (outside Docker)
#   auto  — Probe: Docker profile → host machine → fallback to Docker service
#
# Explicit URLs or empty values pass through unchanged.
# Always outputs a URL on stdout. Never fails.
set -uo pipefail

OLLAMA_PORT="${OLLAMA_PORT:-11434}"
PROBE_TIMEOUT=2

# ── Helpers ─────────────────────────────────────────────────────────────────

is_wsl2() {
  grep -qi microsoft /proc/version 2>/dev/null
}

get_host_url() {
  if is_wsl2; then
    # WSL2: gateway IP reaches the Windows host
    local gateway
    gateway="$(ip route show default 2>/dev/null | awk '{print $3; exit}')"
    if [ -n "${gateway}" ]; then
      echo "http://${gateway}:${OLLAMA_PORT}"
      return
    fi
  fi
  # Native Linux / macOS: extra_hosts mapping in docker-compose.yml
  echo "http://host.docker.internal:${OLLAMA_PORT}"
}

probe_ollama() {
  local url="$1"
  curl -sf --max-time "${PROBE_TIMEOUT}" "${url}/api/tags" >/dev/null 2>&1
}

# ── Resolve ─────────────────────────────────────────────────────────────────

resolve_host() {
  get_host_url
}

resolve_auto() {
  # 1. If local-ollama Docker profile is active, use the Docker service name
  case "${COMPOSE_PROFILES:-}" in
    *local-ollama*)
      echo "http://ollama:${OLLAMA_PORT}"
      return
      ;;
  esac

  # 2. Try host machine
  local host_url
  host_url="$(get_host_url)"
  if probe_ollama "${host_url}"; then
    echo "${host_url}"
    return
  fi

  # 3. Fallback to Docker service name (may not be running yet)
  echo "http://ollama:${OLLAMA_PORT}"
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
  local value="${OLLAMA_BASE_URL:-}"

  case "${value}" in
    host)
      resolve_host
      ;;
    auto)
      resolve_auto
      ;;
    *)
      # Explicit URL or empty — pass through
      echo "${value}"
      ;;
  esac
}

main
