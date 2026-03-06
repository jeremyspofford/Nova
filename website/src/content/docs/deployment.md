---
title: "Deployment"
description: "Development and production commands, GPU overlays, remote GPU setup, and backup/restore."
---

## Quick start

```bash
git clone https://github.com/arialabs/nova.git
cd nova
./setup
```

The setup wizard configures everything and starts all services. See [Quick Start](/quickstart) for details.

## Development commands

| Command | Description |
|---------|-------------|
| `make dev` | Start all services with hot reload (or `docker compose up --build --watch`) |
| `make watch` | Sync Python source into running containers without rebuilding |
| `make logs` | Tail all container logs |
| `make ps` | Show container status |

The dashboard dev server runs on port **5173** via Vite with proxy rules to backend services.

## Production commands

| Command | Description |
|---------|-------------|
| `make build` | Rebuild all Docker images |
| `make up` | Start all services detached |
| `make down` | Stop all services |

In production, the dashboard uses nginx on port **3000**.

## GPU overlays

The setup script auto-detects GPU hardware, but you can manually apply GPU overlays:

### NVIDIA

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

### AMD ROCm

```bash
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d
```

## Remote GPU setup

Nova supports a split topology where the main stack runs on one machine and GPU inference runs on a separate machine (connected over LAN):

1. **On the GPU machine**, run the remote setup script:

```bash
bash <(curl -s https://raw.githubusercontent.com/arialabs/nova/main/scripts/setup-remote-ollama.sh)
```

2. **On the Nova machine**, set the remote URL in `.env`:

```bash
OLLAMA_BASE_URL=http://192.168.1.50:11434
```

3. **Optional: Wake-on-LAN** -- configure WoL so Nova can wake the GPU machine on demand:

```bash
WOL_MAC_ADDRESS=AA:BB:CC:DD:EE:FF
WOL_BROADCAST_IP=192.168.1.255
```

This topology is ideal when you have a low-power always-on server (like a mini PC) running Nova and a separate desktop with a GPU that only powers on when inference is needed.

## Inference backend selection

Nova supports multiple local inference backends beyond Ollama: vLLM, SGLang, and llama.cpp. Each has different strengths for concurrent workloads, CPU-only deployments, or agent pipeline optimization.

See [Inference Backends](/inference-backends) for a full comparison and configuration guide.

Enable backends via Docker Compose profiles in `.env`:

```bash
# Single backend
COMPOSE_PROFILES=local-ollama

# Multiple backends
COMPOSE_PROFILES=local-ollama,local-sglang
```

## Backup and restore

### Via the Recovery UI (recommended)

The Recovery service runs at `http://localhost:8888` and is accessible from the dashboard at `/recovery`. It provides:

- One-click database backup
- Backup history and restore
- Factory reset
- Service health monitoring

The Recovery service only depends on PostgreSQL -- it stays alive even when other services crash, so you always have access to backup and restore.

### Via the CLI

```bash
# Create a backup
make backup

# List available backups
make restore

# Restore a specific backup
make restore F=backups/nova-backup-2025-01-15.sql.gz
```

Backups are stored in the `./backups/` directory.
