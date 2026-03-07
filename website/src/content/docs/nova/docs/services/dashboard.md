---
title: "Dashboard"
description: "React admin UI for managing Nova. Vite dev server on port 5173, nginx production on port 3000."
---

The Dashboard is Nova's web-based admin interface. Built with React, it provides a comprehensive UI for managing agents, monitoring tasks, configuring models, and controlling every aspect of the platform.

## Overview

| Property | Value |
|----------|-------|
| **Dev port** | 5173 (Vite) |
| **Prod port** | 3000 (nginx) |
| **Framework** | React + TypeScript + Vite |
| **Styling** | Tailwind CSS (stone/teal/amber/emerald palette) |
| **State management** | TanStack Query (staleTime=5s, retry=1) |
| **Icons** | Lucide React |
| **Source** | `dashboard/` |

## Pages

| Page | Path | Description |
|------|------|-------------|
| **Chat** | `/` | Streaming chat with the primary agent, model switcher (default landing page) |
| **Tasks** | `/tasks` | Pipeline task board -- submit goals, track state machine progress, cancel in-flight |
| **Pods** | `/pods` | Pod management -- create, configure, enable/disable pods; visual pipeline editor |
| **Usage** | `/usage` | Monthly/weekly/daily usage charts by model with sort toggle |
| **Keys** | `/keys` | API key management -- create, revoke, one-time reveal with copy |
| **Models** | `/models` | Browse all registered models grouped by provider |
| **MCP** | `/mcp` | MCP server management -- add from catalog, configure, reload |
| **Memory Inspector** | `/memory` | Browse, search, and delete stored memories across all tiers |
| **Agent Endpoints** | `/agent-endpoints` | External agent delegation configuration |
| **Settings** | `/settings` | Platform configuration (see below) |
| **Recovery** | `/recovery` | Backup/restore, factory reset, service management |
| **Remote Access** | `/remote-access` | Cloudflare Tunnel and Tailscale setup wizards |

## Settings page sections

The Settings page is organized into these sections:

1. **Nova Identity** -- AI name, greeting message, and persona/soul (configures how the AI presents itself)
2. **Platform Defaults** -- task history retention
3. **LLM Routing** -- routing strategy (local-only, local-first, cloud-only, cloud-first), Ollama URL, intelligent routing
4. **Provider Status** -- API key presence, ping latency, test button per provider
5. **Context Budgets** -- tune the system/tools/memory/history/working percentage split
6. **Admin Secret** -- update the admin authentication secret
7. **Remote Access** -- Cloudflare Tunnel and Tailscale configuration
8. **Recovery & Services** -- backup/restore, factory reset, service management
9. **System Status** -- live status of Queue Worker, Reaper, and MCP Servers
10. **Appearance** -- theme presets and accent color palette
11. **Notifications** -- desktop notification preferences
12. **Developer Resources** -- links to API docs and service ports

## Proxy configuration

In development, the Vite dev server proxies API requests to backend services:

| Prefix | Target |
|--------|--------|
| `/api` | Orchestrator (port 8000) |
| `/v1` | LLM Gateway (port 8001) |
| `/recovery-api` | Recovery Service (port 8888) |

In production, nginx handles the same proxy rules.

## API client

All API calls go through `apiFetch<T>()` in `src/api.ts`, which:

- Adds the `X-Admin-Secret` header from localStorage
- Handles JSON serialization/deserialization
- Provides typed responses via TypeScript generics

## Startup behavior

The Dashboard depends only on the Recovery service at startup. While other services are coming online, it shows a startup screen with service health status. Once the Orchestrator reports healthy, the full UI becomes available.

## Build verification

```bash
cd dashboard && npm run build
```

This runs the TypeScript compiler and Vite build. A successful build confirms type safety across all components.

## Implementation notes

- **Functional components only** -- no class components; hooks and TanStack Query for all state
- **TanStack Query** -- server state management with 5-second stale time and 1 retry; provides automatic background refetching
- **Tailwind CSS** -- utility-first styling with a consistent stone/teal/amber/emerald color palette throughout
- **No client-side routing library for auth** -- admin secret is stored in localStorage and sent as a header on every request
