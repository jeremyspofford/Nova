---
title: "Quick Start"
description: "Get Nova running in under five minutes with Docker Compose."
---

## Prerequisites

- [Docker Desktop](https://docker.com/products/docker-desktop) (includes Docker Compose)
- [Git](https://git-scm.com/)
- (Optional) [GNU Make](https://www.gnu.org/software/make/) for the convenience commands — pre-installed on most Linux/macOS systems; on Windows use WSL or `choco install make`.

No Python, Node.js, or database installs required -- everything runs in containers.

## Install — copy/paste

```bash
git clone https://github.com/jeremyspofford/nova.git
cd nova
./install
```

That's it. The wizard handles prereq checks, mode selection, optional provider keys, model pulls (if applicable), and bringing every service up.

## What the setup wizard does

1. Copies `.env.example` to `.env` if it doesn't exist
2. Detects GPU availability (NVIDIA / AMD ROCm)
3. Asks how you want to use Nova (default is `hybrid`):

   ```text
   Nova can run with local AI, cloud AI, or both.

     [1] hybrid     — bundle Ollama for local AI, fall back to cloud (recommended)
     [2] local-only — bundle Ollama, never use cloud (privacy/offline-friendly)
     [3] cloud-only — no bundled Ollama, only use cloud APIs (lighter setup)

   Choice [1/2/3] (default 1):
   ```

   Just hit enter for `hybrid`. After install, mode changes (and pointing Nova at an external Ollama / vLLM instance) live in Settings → AI & Models — no scripts.
4. Configures LLM provider API keys
5. Pulls Ollama models for hybrid/local-only modes (skipped under cloud-only)
6. Starts all services via Docker Compose

When it finishes, open **<http://localhost:3000>** to access the dashboard.

## Remote GPU (optional)

If you have a separate machine with a GPU for AI inference:

```bash
# Run this ON the GPU machine:
bash <(curl -s https://raw.githubusercontent.com/jeremyspofford/nova/main/scripts/setup-remote-ollama.sh)
```

Then re-run `./install` on the Nova machine and choose "Remote GPU". The wizard will ask for the GPU machine's IP address and configure Wake-on-LAN if desired.

## Manual configuration

If you prefer to skip the wizard:

```bash
cp .env.example .env
# Edit .env with your preferred settings
make dev
```

See [Configuration](/nova/docs/configuration) for all available settings.

## Verify everything is running

Check container status:

```bash
make ps
```

All core services should show as healthy. Hit the health endpoints to confirm:

| Service | Health endpoint |
|---------|----------------|
| dashboard | `http://localhost:3000` |
| orchestrator | `http://localhost:8000/health/live` |
| llm-gateway | `http://localhost:8001/health/live` |
| memory-service | `http://localhost:8002/health/live` |
| chat-api | `http://localhost:8080/health/live` |
| cortex | `http://localhost:8100/health/live` |
| recovery | `http://localhost:8888/health/live` |

You can also test the chat interface at `http://localhost:8080/` for an interactive demo.

## Next steps

- [Architecture](/nova/docs/architecture) -- understand how the services fit together
- [Configuration](/nova/docs/configuration) -- configure providers, models, and routing
- [Deployment](/nova/docs/deployment) -- production commands, GPU overlays, backups
