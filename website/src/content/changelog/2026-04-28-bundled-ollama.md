---
title: "Inference modes — bundled Ollama by default"
date: 2026-04-28
---

Nova now asks how you'd like to use it on first run, and ships sensible defaults for each option:

- **hybrid** (default) — bundles Ollama for local AI, falls back to cloud providers when needed. Best of both worlds. First-run downloads ~5.4 GB of starter models (`qwen2.5:1.5b`, `qwen2.5:7b`, `nomic-embed-text`).
- **local-only** — bundles Ollama, never uses cloud. Privacy-first or offline-friendly. Same ~5.4 GB starter models.
- **cloud-only** — does not bundle Ollama at all (no image pull, no container, no model downloads). Lightest footprint, requires cloud API keys.

After install, switching modes (and pointing Nova at an external Ollama / vLLM instance like `http://192.168.x.y:11434`) lives in the dashboard — Settings → AI & Models, no scripts. The first-install prompt is just the bootstrap step before the dashboard is running.

Under the hood: a single user-facing `NOVA_INFERENCE_MODE` knob now derives both `COMPOSE_PROFILES` (whether the bundled `ollama` Compose service ships and starts) and `LLM_ROUTING_STRATEGY` (how the gateway picks providers). The `setup.sh` wizard writes both to `.env` idempotently, preserving any unrelated profiles you already have set.

**Heads-up for existing installs:** if your `.env` previously had `OLLAMA_BASE_URL=auto` or `OLLAMA_BASE_URL=host` and you depended on the gateway probing your host's Ollama instance (Windows/macOS native install, remote LAN box, etc.), those values now resolve to the bundled service (`http://ollama:11434`) instead. The brittle subprocess-based probe (and `scripts/resolve-ollama-url.sh`) is gone. To keep using your host's Ollama, set `OLLAMA_BASE_URL` to a literal URL — e.g. `OLLAMA_BASE_URL=http://host.docker.internal:11434` for a same-host install, or `OLLAMA_BASE_URL=http://192.168.x.y:11434` for a LAN box.
