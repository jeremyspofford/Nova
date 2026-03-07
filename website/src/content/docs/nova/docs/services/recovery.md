---
title: "Recovery Service"
description: "Backup/restore, factory reset, service management, and environment configuration. Port 8888."
---

The Recovery Service is Nova's resilience layer. It is designed to stay alive when all other Nova services are down, providing backup/restore, factory reset, service management, and environment configuration capabilities.

## At a glance

| Property | Value |
|----------|-------|
| **Port** | 8888 |
| **Framework** | FastAPI + asyncpg + Docker SDK |
| **Dependencies** | PostgreSQL + Docker socket only |
| **Source** | `recovery-service/` |

The Recovery Service intentionally has minimal dependencies. It connects directly to PostgreSQL (for backups) and the Docker socket (for container management). It does not depend on Redis, the Orchestrator, or any other Nova service -- this ensures it remains operational even during a complete system failure.

## Key responsibilities

- **Database backup** -- create, list, restore, and delete PostgreSQL backups
- **Factory reset** -- selective or complete data reset by category
- **Service management** -- list container status, restart individual services or all services
- **Environment management** -- read and update `.env` file variables (whitelist enforced, secrets masked)
- **Compose profile management** -- start/stop optional Docker Compose profiles (Cloudflare Tunnel, Tailscale)
- **System status** -- rich overview combining service health, database stats, and backup info

## Key endpoints

### Status

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/recovery/status` | Rich status overview: services, DB stats, backup info |

### Service management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/recovery/services` | -- | List all Nova containers and their status |
| POST | `/api/v1/recovery/services/{name}/restart` | Admin | Restart a specific service |
| POST | `/api/v1/recovery/services/restart-all` | Admin | Restart all services |

### Backups

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/recovery/backups` | -- | List available backups |
| POST | `/api/v1/recovery/backups` | Admin | Create a new backup |
| POST | `/api/v1/recovery/backups/{filename}/restore` | Admin | Restore from a backup |
| DELETE | `/api/v1/recovery/backups/{filename}` | Admin | Delete a backup |

### Factory reset

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/recovery/factory-reset/categories` | List data categories available for reset |

### Environment management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/recovery/env` | Admin | Read whitelisted env vars (secrets masked) |
| PATCH | `/api/v1/recovery/env` | Admin | Update `.env` keys (whitelist enforced) |

### Compose profiles

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/recovery/compose-profiles` | Admin | Start/stop a compose profile (e.g., cloudflare-tunnel, tailscale) |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe (checks DB connectivity) |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | -- |
| `ADMIN_SECRET` | Admin authentication secret | -- |
| `BACKUP_DIR` | Directory for storing backups | `/backups` |
| `PORT` | Service port | `8888` |

## Backup and restore

Backups are full PostgreSQL dumps stored in the configured backup directory (mounted as a Docker volume at `/backups`, mapped to `./backups/` on the host).

**Create a backup via the API:**

```bash
curl -X POST http://localhost:8888/api/v1/recovery/backups \
  -H "X-Admin-Secret: your-admin-secret"
```

**Or via the command line:**

```bash
make backup               # Create a backup
make restore               # List available backups
make restore F=<file>      # Restore a specific backup
```

The Recovery page in the Dashboard provides a visual interface for the same operations.

## Implementation notes

- **Docker SDK** -- uses the Docker SDK for Python to interact with containers via the Docker socket, enabling container inspection, restart, and status checks
- **Whitelist enforcement** -- environment variable reads and writes are restricted to a whitelist of known Nova configuration keys; arbitrary env vars cannot be accessed
- **Secret masking** -- when reading env vars, sensitive values (API keys, secrets) are masked in the response
- **Auth** -- all mutating endpoints require the `X-Admin-Secret` header; read-only endpoints (service list, backup list) are open
- **Compose profiles** -- the service manages Docker Compose profiles for optional services like Cloudflare Tunnel and Tailscale, enabling the Remote Access page in the Dashboard to start/stop these services
