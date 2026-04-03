# Embedded Code Editor Service

**Date:** 2026-04-03
**Status:** Approved

## Problem

Nova is a complete autonomous AI platform, but users still have to leave the dashboard to edit code. For a DevOps engineer working with Nova, tabbing out to a separate IDE breaks the single-pane-of-glass experience. The editor should live inside Nova.

## Decision Summary

| Decision | Choice |
|---|---|
| Editor technology | code-server (VS Code) and ttyd+neovim as selectable flavors |
| Architecture | Two separate Docker services, two profiles, one active at a time |
| UI integration | Embedded full-width dashboard tab with iframe, pop-out button |
| Default workspace | Configurable path, default `~/.nova/workspace` |
| Config portability | Bind-mount by default, optional git dotfiles repo. Config path is user-configurable — can point at Nova's isolated path or their real config directory |
| Agent integration | Shared filesystem only (v1). Deep integration (custom extensions/plugins) is a future phase |
| Service pattern | Dumb containers with Docker healthcheck, no FastAPI wrapper |

## Docker Services

### editor-vscode

- **Image:** `linuxserver/code-server`
- **Profile:** `editor-vscode`
- **Port:** `8140:8443` (code-server uses 8443 internally)
- **Volumes:**
  - `${EDITOR_WORKSPACE:-${HOME}/.nova/workspace}:/workspace:rw` — working directory
  - `${VSCODE_CONFIG_PATH:-./data/editor-config/vscode}:/config:rw` — settings, extensions, keybindings
  - `${HOME}:${HOME}:ro` — read-only home access for browsing other files
- **Environment:** `DEFAULT_WORKSPACE=/workspace`, `PUID`/`PGID` for file permissions
- **Healthcheck:** curl against code-server's built-in `/healthz`
- **Dependencies:** None — editor is fully independent of other Nova services

### editor-neovim

- **Image:** Custom Dockerfile (Alpine-based)
- **Profile:** `editor-neovim`
- **Port:** `8140:7681` (ttyd default)
- **Volumes:**
  - `${EDITOR_WORKSPACE:-${HOME}/.nova/workspace}:/workspace:rw` — working directory
  - `${NEOVIM_CONFIG_PATH:-./data/editor-config/neovim}:/root/.config/nvim:rw` — neovim config
  - `${HOME}:${HOME}:ro` — read-only home access
- **Healthcheck:** curl against ttyd's HTTP port
- **Entrypoint:** `ttyd --writable --port 7681 nvim /workspace`

Both services bind to host port 8140. Only one runs at a time.

## Neovim Container (Custom Dockerfile)

**Base:** `alpine:3.20`

**Packages:**
- neovim, ttyd — the editor and web terminal
- git, ripgrep, fd — standard dev tooling
- nodejs, python3, py3-pip — needed by neovim plugins (LSPs, treesitter, Mason)
- curl, openssh-client — git operations and general utility

**Entrypoint script:**
1. If `EDITOR_DOTFILES_REPO` is set and config dir is empty, `git clone` into neovim config path. If already cloned, `git pull`.
2. Launch `ttyd --writable --port 7681 nvim /workspace`

**Not included:** No language-specific runtimes beyond node/python. No preloaded plugin managers — user configs bootstrap themselves on first launch.

**Image size:** ~150-200MB.

## Nginx Proxy

Two location blocks in `dashboard/nginx.conf`:

```nginx
location /editor-vscode/ {
    set $editor_vscode http://editor-vscode:8443;
    rewrite ^/editor-vscode/(.*) /$1 break;
    proxy_pass $editor_vscode;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /editor-neovim/ {
    set $editor_neovim http://editor-neovim:7681;
    rewrite ^/editor-neovim/(.*) /$1 break;
    proxy_pass $editor_neovim;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Dashboard knows which flavor is active and iframes the correct path. Docker DNS only resolves running containers — requests to a stopped editor's path simply fail, and the dashboard handles this gracefully.

## Dashboard Integration

### Routes

- New full-width route: `/editor` in `App.tsx`
- Existing `/editors` route renamed to `/ide-connections` (external IDE configuration)
- Sidebar: "Editor" under Infrastructure opens the embedded editor. "IDE Connections" (renamed) remains for external editor setup.

### Editor Page (`pages/Editor.tsx`)

**When no editor is running:**
- Shows a setup prompt: "No editor running. Start one in Settings > Editor."
- Direct link to Settings editor section.

**When editor is running:**
- Full-viewport iframe pointing at the active editor's nginx path (`/editor-vscode/` or `/editor-neovim/`)
- Thin top bar with: flavor indicator, workspace path, pop-out button
- Pop-out button opens the proxied URL in a new browser tab

**Detection:** Page probes both nginx paths on mount. Whichever responds is the active editor.

### Settings Section (`pages/settings/EditorSection.tsx`)

| Field | Type | Default |
|---|---|---|
| Editor Flavor | Dropdown: VS Code / Neovim | VS Code |
| Workspace Path | Text input | `~/.nova/workspace` |
| VS Code Config Path | Text input | `./data/editor-config/vscode` |
| Neovim Config Path | Text input | `./data/editor-config/neovim` |
| Dotfiles Repo | Text input (optional) | empty |

**Service controls:**
- Start / Stop button — calls `manageComposeProfile()`
- Status badge — running/stopped via `ServiceStatusBadge`
- Flavor switch: stop current profile, update env, start new profile

**Persistence:** All values stored via `patchEnv()` to `.env`. Survive container restarts.

## Configuration Flow

### First-time setup
1. User goes to Settings > Editor
2. Picks flavor (default: VS Code), optionally adjusts paths
3. Clicks "Start Editor"
4. Dashboard calls `patchEnv()` then `manageComposeProfile('editor-vscode', 'start')`
5. Container pulls image on first run (one-time), starts, healthcheck passes
6. User navigates to "Editor" in sidebar — iframe loads

### Switching flavors
1. User changes dropdown in Settings
2. Dashboard stops current profile, patches env, starts new profile
3. Editor page iframes the new flavor's path on next visit

### Container restarts / rebuilds
- Config survives via bind-mounted volumes
- Dotfiles repo re-pulls on startup if configured
- No data loss

## Agent Integration (v1)

Shared filesystem only. Nova's agents read/write `/workspace` as they always have. The editor is another consumer of the same volume. No coordination protocol, no locks, no sync — the filesystem is the interface.

**Future phase (out of scope):** Custom VS Code extension and neovim plugin for inline agent activity, diffs, and task context.

## New Environment Variables

| Variable | Default | Description |
|---|---|---|
| `EDITOR_FLAVOR` | `vscode` | Active editor: `vscode` or `neovim` |
| `EDITOR_WORKSPACE` | `${HOME}/.nova/workspace` | Workspace path mounted into editor |
| `VSCODE_CONFIG_PATH` | `./data/editor-config/vscode` | VS Code settings/extensions persist here |
| `NEOVIM_CONFIG_PATH` | `./data/editor-config/neovim` | Neovim config persists here |
| `EDITOR_DOTFILES_REPO` | (empty) | Git repo cloned into config dir on startup |

## Port Allocation

Editor service: **8140** (both flavors, mutually exclusive)

## Files to Create/Modify

**New files:**
- `editor-vscode/` — directory (minimal, mostly compose config since we use upstream image)
- `editor-neovim/Dockerfile` — custom Alpine + neovim + ttyd image
- `editor-neovim/entrypoint.sh` — dotfiles clone + ttyd launch
- `dashboard/src/pages/Editor.tsx` — embedded editor page
- `dashboard/src/pages/settings/EditorSection.tsx` — editor settings

**Modified files:**
- `docker-compose.yml` — two new service definitions
- `dashboard/nginx.conf` — two new location blocks
- `dashboard/src/App.tsx` — new `/editor` route, rename `/editors` to `/ide-connections`
- `dashboard/src/components/layout/Sidebar.tsx` — add "Editor" nav item, rename "Editors" to "IDE Connections"
- `dashboard/src/pages/Settings.tsx` — add Editor section to nav groups
- `.env.example` — new editor variables
