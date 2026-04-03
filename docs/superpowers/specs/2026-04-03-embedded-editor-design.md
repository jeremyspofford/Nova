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
- **Port:** Internal only (8443) — no host port binding. Accessed exclusively via nginx proxy.
- **Volumes:**
  - `${EDITOR_WORKSPACE:-${HOME}/.nova/workspace}:/workspace:rw` — working directory
  - `${VSCODE_CONFIG_PATH:-./data/editor-config/vscode}:/config:rw` — settings, extensions, keybindings
  - `${HOME}:${HOME}:ro` — read-only home access for browsing other files
- **Environment:** `DEFAULT_WORKSPACE=/workspace`, `PUID`/`PGID` for file permissions, `PORT=8443` (explicit), `HASHED_PASSWORD=""` (linuxserver uses `HASHED_PASSWORD` — setting empty disables auth). Note: verify against current linuxserver/code-server docs at implementation time, as env var names may change between versions.
- **Command args:** `--proxy-base-path /editor-vscode` (required for subpath proxy — without this, code-server serves assets at `/` and every resource 404s behind nginx)
- **Healthcheck:** curl against code-server's built-in `/healthz`
- **Dependencies:** None — editor is fully independent of other Nova services

### editor-neovim

- **Image:** Custom Dockerfile (Alpine-based)
- **Profile:** `editor-neovim`
- **Port:** Internal only (7681) — no host port binding. Accessed exclusively via nginx proxy.
- **Volumes:**
  - `${EDITOR_WORKSPACE:-${HOME}/.nova/workspace}:/workspace:rw` — working directory
  - `${NEOVIM_CONFIG_PATH:-./data/editor-config/neovim}:/root/.config/nvim:rw` — neovim config
  - `${HOME}:${HOME}:ro` — read-only home access
- **Healthcheck:** curl against ttyd's HTTP port
- **Entrypoint:** `ttyd --writable --base-path /editor-neovim --port 7681 nvim /workspace`

### Auth Posture

Neither editor exposes a host port. They are only reachable through the dashboard's nginx proxy, which sits behind Nova's existing auth layer (`REQUIRE_AUTH` / JWT / admin secret). code-server's built-in password auth is disabled. ttyd runs without `--credential`. This is a deliberate choice — Nova owns the auth boundary, and adding a second auth layer inside the iframe would be a broken UX (two login prompts).

### Network

Both services are internal-only on the `nova-internal` Docker network. No host port binding means no direct access bypassing Nova's auth. Only the dashboard nginx proxy can reach them.

### Security Note: Home Directory Mount

Both editors mount `${HOME}:${HOME}:ro` for browsing files outside the workspace. This gives the editor read access to the entire home directory, including `.ssh/`, `.aws/`, `.gnupg/`, and other credential stores. This is acceptable for a single-user local deployment (the user already has access to their own home), but users should evaluate whether this mount is necessary. The Settings UI config path fields provide an alternative — point the workspace at a specific project directory rather than relying on home-directory browsing. In multi-user or exposed deployments, this mount should be removed or scoped to a narrower path.

## Neovim Container (Custom Dockerfile)

**Base:** `alpine:3.20`

**Packages:**
- neovim, ttyd — the editor and web terminal
- git, ripgrep, fd — standard dev tooling
- nodejs, python3, py3-pip — needed by neovim plugins (LSPs, treesitter, Mason)
- curl, openssh-client — git operations and general utility

**Entrypoint script:**
1. If `EDITOR_DOTFILES_REPO` is set and config dir is empty, `git clone` into neovim config path. If already cloned, `git pull`.
2. Launch `ttyd --writable --base-path /editor-neovim --port 7681 nvim /workspace`

**Not included:** No language-specific runtimes beyond node/python. No preloaded plugin managers — user configs bootstrap themselves on first launch.

**Image size:** ~150-200MB.

## Nginx Proxy

Two location blocks in `dashboard/nginx.conf`:

```nginx
location /editor-vscode/ {
    set $editor_vscode http://editor-vscode:8443;
    proxy_pass $editor_vscode;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}

location /editor-neovim/ {
    set $editor_neovim http://editor-neovim:7681;
    proxy_pass $editor_neovim;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

**Important: no `rewrite` strip-prefix.** This diverges from every other location block in nginx.conf, which strips the prefix before forwarding. The editor blocks intentionally keep the prefix because both editors are configured with their base path (`--proxy-base-path /editor-vscode` for code-server, `--base-path /editor-neovim` for ttyd) and expect requests to arrive with the prefix intact. Add an inline comment in the nginx config explaining this — otherwise a future maintainer will "fix" it to match the existing pattern and break the editor.

Timeouts set to 3600s (1 hour) for WebSocket connections — editors have long idle periods between keystrokes, and nginx's default 60s read timeout would kill the session.

Dashboard knows which flavor is active and iframes the correct path. Docker DNS only resolves running containers — requests to a stopped editor's path return 502, and the dashboard handles this gracefully.

## Dashboard Integration

### Routes

- New full-width route: `/editor` in `App.tsx`
- Existing `/editors` route renamed to `/ide-connections` (external IDE configuration). Add `<Navigate>` redirect from `/editors` to `/ide-connections` to avoid breaking bookmarks.
- Sidebar: "Editor" under Infrastructure opens the embedded editor. "IDE Connections" (renamed) remains for external editor setup.

### Editor Page (`pages/Editor.tsx`)

**When no editor is running:**
- Shows a setup prompt: "No editor running. Start one in Settings > Editor."
- Direct link to Settings editor section.

**When editor is running:**
- Full-viewport iframe pointing at the active editor's nginx path (`/editor-vscode/` or `/editor-neovim/`)
- Thin top bar with: flavor indicator, workspace path, pop-out button
- Pop-out button opens the proxied URL in a new browser tab

**Detection:** Page probes both nginx paths on mount, then polls every 3s while in a non-ready state. Three states:

- **Running** — one path returns 200. Render the iframe.
- **Starting** — both return 502, but a start action was triggered recently (track via local state or a timestamp). Show a loading spinner with "Editor starting..." Poll until 200 or timeout (60s).
- **Stopped** — both return 502, no recent start action. Show "No editor running. Start one in Settings > Editor." If an editor was previously running in this session, show "Editor stopped unexpectedly" with a restart link.

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

Editor services are internal-only (no host port binding):
- **editor-vscode:** 8443 (container-internal)
- **editor-neovim:** 7681 (container-internal)

Accessed exclusively through dashboard nginx proxy at `/editor-vscode/` and `/editor-neovim/`.

## Files to Create/Modify

**New files:**
- `editor-vscode/` — directory (minimal, mostly compose config since we use upstream image)
- `editor-neovim/Dockerfile` — custom Alpine + neovim + ttyd image
- `editor-neovim/entrypoint.sh` — dotfiles clone + ttyd launch
- `dashboard/src/pages/Editor.tsx` — embedded editor page
- `dashboard/src/pages/settings/EditorSection.tsx` — editor settings

**Modified files:**
- `docker-compose.yml` — two new service definitions (internal-only, no host port)
- `dashboard/nginx.conf` — two new location blocks with WebSocket upgrade and 1h timeouts
- `dashboard/src/App.tsx` — new `/editor` route, rename `/editors` to `/ide-connections`, add redirect from `/editors`
- `dashboard/src/components/layout/Sidebar.tsx` — add "Editor" nav item, rename "Editors" to "IDE Connections"
- `dashboard/src/pages/Settings.tsx` — add Editor section to nav groups
- `recovery-service/app/routes.py` — add to `PROFILE_MAP` (hard-coded allowlist that rejects unknown profiles with 400):
  ```python
  "editor-vscode": "editor-vscode",
  "editor-neovim": "editor-neovim",
  ```
- `.env.example` — new editor variables
