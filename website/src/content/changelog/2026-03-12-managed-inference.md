---
title: "Managed Inference Backends"
date: 2026-03-12
---

- Added managed inference backend lifecycle -- select vLLM or Ollama from the dashboard, Nova handles container start/stop/health
- Hardware detection: auto-detects GPU vendor, VRAM, Docker GPU runtime at setup and runtime
- New `LocalInferenceProvider` in LLM gateway wraps the active backend with 5-second config cache
- Backend switching with drain protocol: zero dropped requests when switching between backends
- New Settings section: Local Inference (AI & Models tab) with backend selector, live status, hardware info
- Recovery service now manages inference containers via Docker Compose profiles with health monitoring (30s interval, exponential backoff restart)
- vLLM model discovery via `/v1/models` endpoint
- In-flight request tracking (`GET /health/inflight`) enables graceful drain during backend switches
- Redis db7 allocated for recovery service (`nova:system:*` namespace for system facts)
