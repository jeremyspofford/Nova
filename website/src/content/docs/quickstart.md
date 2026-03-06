---
title: "Quick Start"
description: "Get Nova running in under five minutes with Docker Compose."
---

## Prerequisites

- [Docker Desktop](https://docker.com/products/docker-desktop) (includes Docker Compose)
- [GNU Make](https://www.gnu.org/software/make/) (pre-installed on most Linux/macOS systems; on Windows use WSL or install via `choco install make`)
- [Git](https://git-scm.com/)

No Python, Node.js, or database installs required -- everything runs in containers.

## Install

```bash
git clone https://github.com/arialabs/nova.git
cd nova
./setup
```

The setup wizard handles the rest.

## What the setup wizard does

1. Copies `.env.example` to `.env` if it doesn't exist
2. Detects GPU availability (NVIDIA / AMD ROCm)
3. Asks about your deployment mode (cloud-only, local model serving, remote GPU)
4. Configures LLM provider API keys
5. Pulls selected Ollama models (if using local inference)
6. Starts all services via Docker Compose

When it finishes, open **http://localhost:3001** to access the dashboard.

## Remote GPU (optional)

If you have a separate machine with a GPU for AI inference:

```bash
# Run this ON the GPU machine:
bash <(curl -s https://raw.githubusercontent.com/arialabs/nova/main/scripts/setup-remote-ollama.sh)
```

Then re-run `./setup` on the Nova machine and choose "Remote GPU". The wizard will ask for the GPU machine's IP address and configure Wake-on-LAN if desired.

## Manual configuration

If you prefer to skip the wizard:

```bash
cp .env.example .env
# Edit .env with your preferred settings
make dev
```

See [Configuration](/configuration) for all available settings.

## Verify everything is running

Check container status:

```bash
make ps
```

All 7 core services should show as healthy. Hit the health endpoints to confirm:

| Service | Health endpoint |
|---------|----------------|
| orchestrator | `http://localhost:8000/health/live` |
| llm-gateway | `http://localhost:8001/health/live` |
| memory-service | `http://localhost:8002/health/live` |
| chat-api | `http://localhost:8080/health/live` |
| dashboard | `http://localhost:3001` |
| recovery | `http://localhost:8888/health/live` |

You can also test the chat interface at `http://localhost:8080/` for an interactive demo.

## Next steps

- [Architecture](/architecture) -- understand how the services fit together
- [Configuration](/configuration) -- configure providers, models, and routing
- [Deployment](/deployment) -- production commands, GPU overlays, backups
