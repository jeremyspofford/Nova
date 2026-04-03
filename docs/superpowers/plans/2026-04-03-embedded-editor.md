# Embedded Code Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add VS Code (code-server) and Neovim (ttyd) as embeddable, selectable editor flavors inside the Nova dashboard.

**Architecture:** Two Docker services (one per editor flavor) behind nginx reverse proxy, embedded in the dashboard via iframe on a new `/editor` route. Settings UI manages flavor selection, workspace paths, config paths, and service lifecycle via the existing recovery API.

**Tech Stack:** Docker Compose profiles, linuxserver/code-server, Alpine + ttyd + neovim, nginx WebSocket proxy, React + TypeScript (dashboard)

**Spec:** `docs/superpowers/specs/2026-04-03-embedded-editor-design.md`

---

## File Structure

**New files:**
| File | Responsibility |
|------|----------------|
| `editor-neovim/Dockerfile` | Alpine image with neovim, ttyd, dev tooling |
| `editor-neovim/entrypoint.sh` | Dotfiles clone/pull + ttyd launch |
| `dashboard/src/pages/Editor.tsx` | Embedded editor page (iframe, detection, three-state UI) |
| `dashboard/src/pages/settings/EditorSection.tsx` | Editor settings (flavor, paths, dotfiles, start/stop) |
| `editor-vscode/.gitkeep` | Placeholder for VS Code editor service directory |

**Modified files:**
| File | Change |
|------|--------|
| `docker-compose.yml` | Two new service definitions after vaultwarden |
| `dashboard/nginx.conf` | Two new location blocks before SPA fallback |
| `recovery-service/app/routes.py:250-254` | Add editor profiles to PROFILE_MAP |
| `dashboard/src/App.tsx:167-200` | New /editor route, rename /editors, add redirect |
| `dashboard/src/components/layout/Sidebar.tsx:59-66` | Add Editor nav item, rename Editors |
| `dashboard/src/pages/Settings.tsx:90-147` | Add editor section to NAV_GROUPS |
| `.env.example:129` | New editor env vars section |

---

### Task 1: Neovim Container Image

**Files:**
- Create: `editor-neovim/Dockerfile`
- Create: `editor-neovim/entrypoint.sh`

- [ ] **Step 1: Create the entrypoint script**

```bash
#!/bin/sh
set -e

NVIM_CONFIG_DIR="${NVIM_CONFIG_DIR:-/root/.config/nvim}"

# Clone or pull dotfiles repo if configured
if [ -n "$EDITOR_DOTFILES_REPO" ]; then
  if [ ! -d "$NVIM_CONFIG_DIR/.git" ]; then
    echo "[editor-neovim] Cloning dotfiles from $EDITOR_DOTFILES_REPO"
    git clone "$EDITOR_DOTFILES_REPO" "$NVIM_CONFIG_DIR"
  else
    echo "[editor-neovim] Pulling latest dotfiles"
    cd "$NVIM_CONFIG_DIR" && git pull --ff-only || true
  fi
fi

echo "[editor-neovim] Starting ttyd + neovim"
exec ttyd --writable --base-path /editor-neovim --port 7681 nvim /workspace
```

- [ ] **Step 2: Create the Dockerfile**

```dockerfile
FROM alpine:3.20

RUN apk add --no-cache \
    neovim \
    ttyd \
    git \
    ripgrep \
    fd \
    nodejs \
    npm \
    python3 \
    py3-pip \
    curl \
    openssh-client \
    bash

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace

EXPOSE 7681

HEALTHCHECK --interval=5s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -sf http://localhost:7681/editor-neovim/ || exit 1

ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 3: Build and verify the image**

Run: `docker build -t nova-editor-neovim editor-neovim/`
Expected: Successful build, image ~150-200MB

Run: `docker images nova-editor-neovim --format '{{.Size}}'`
Expected: Size under 250MB

- [ ] **Step 4: Smoke test the container**

Run: `docker run --rm -d --name test-neovim -p 7681:7681 nova-editor-neovim ttyd --writable --port 7681 nvim`
Then: `curl -sf http://localhost:7681/ | head -c 200`
Expected: HTML response from ttyd
Cleanup: `docker stop test-neovim`

- [ ] **Step 5: Create editor-vscode placeholder directory**

```bash
mkdir -p editor-vscode && touch editor-vscode/.gitkeep
```

This directory exists as a placeholder for the VS Code editor service. The upstream `linuxserver/code-server` image is used directly — no custom Dockerfile needed.

- [ ] **Step 6: Commit**

```bash
git add editor-neovim/ editor-vscode/
git commit -m "feat(editor): add neovim + ttyd container image and vscode placeholder"
```

---

### Task 2: Docker Compose Service Definitions

**Files:**
- Modify: `docker-compose.yml` (insert after vaultwarden block, ~line 753)

- [ ] **Step 1: Add editor-vscode service**

Insert after the vaultwarden service block (after line 753 in `docker-compose.yml`), before the `dashboard:` service:

```yaml
  # ── Embedded Editors (optional, one active at a time) ────────────────────────
  # NOTE: Both editors are internal-only (no host port). Access via dashboard
  # nginx proxy at /editor-vscode/ or /editor-neovim/.
  editor-vscode:
    image: linuxserver/code-server:latest
    container_name: nova-editor-vscode
    profiles: ["editor-vscode"]
    restart: unless-stopped
    environment:
      - DEFAULT_WORKSPACE=/workspace
      - PUID=${PUID:-1000}
      - PGID=${PGID:-1000}
      - PORT=8443
      - HASHED_PASSWORD=
    volumes:
      - ${EDITOR_WORKSPACE:-${HOME}/.nova/workspace}:/workspace:rw
      - ${VSCODE_CONFIG_PATH:-./data/editor-config/vscode}:/config:rw
      - ${HOME}:${HOME}:ro
    # linuxserver/code-server wraps coder/code-server — pass proxy-base-path
    # so asset URLs include the /editor-vscode/ prefix for nginx subpath proxy.
    command: --proxy-base-path /editor-vscode
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8443/healthz"]
      <<: *nova-healthcheck
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "3"
    networks:
      - nova-internal
```

- [ ] **Step 2: Add editor-neovim service**

Insert directly after editor-vscode:

```yaml
  editor-neovim:
    build:
      context: .
      dockerfile: editor-neovim/Dockerfile
    container_name: nova-editor-neovim
    profiles: ["editor-neovim"]
    restart: unless-stopped
    environment:
      - EDITOR_DOTFILES_REPO=${EDITOR_DOTFILES_REPO:-}
      - NVIM_CONFIG_DIR=/root/.config/nvim
    volumes:
      - ${EDITOR_WORKSPACE:-${HOME}/.nova/workspace}:/workspace:rw
      - ${NEOVIM_CONFIG_PATH:-./data/editor-config/neovim}:/root/.config/nvim:rw
      - ${HOME}:${HOME}:ro
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:7681/editor-neovim/"]
      <<: *nova-healthcheck
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "3"
    networks:
      - nova-internal
```

- [ ] **Step 3: Validate compose config**

Run: `docker compose config --services | sort`
Expected: Output includes `editor-neovim` and `editor-vscode` among all services

Run: `docker compose config 2>&1 | grep -i error`
Expected: No output (no config errors)

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(editor): add editor-vscode and editor-neovim compose services"
```

---

### Task 3: Recovery Service — PROFILE_MAP Update

**Files:**
- Modify: `recovery-service/app/routes.py:250-254`

- [ ] **Step 1: Add editor profiles to PROFILE_MAP**

In `recovery-service/app/routes.py`, update the `PROFILE_MAP` dict at line 250:

```python
PROFILE_MAP = {
    "cloudflare-tunnel": "cloudflared",
    "tailscale": "tailscale",
    "bridges": "chat-bridge",
    "editor-vscode": "editor-vscode",
    "editor-neovim": "editor-neovim",
}
```

- [ ] **Step 2: Verify no syntax errors**

Run: `cd recovery-service && python3 -c "from app.routes import PROFILE_MAP; print(PROFILE_MAP)" 2>&1`
Expected: Dict with 5 entries including both editor profiles

- [ ] **Step 3: Commit**

```bash
git add recovery-service/app/routes.py
git commit -m "feat(editor): add editor profiles to recovery PROFILE_MAP"
```

---

### Task 4: Nginx Proxy Configuration

**Files:**
- Modify: `dashboard/nginx.conf` (insert before SPA fallback at line 83)

- [ ] **Step 1: Add editor location blocks**

Insert before the SPA fallback block (`location /` at line 84) in `dashboard/nginx.conf`:

```nginx
    # Proxy Embedded Editors — VS Code (code-server) and Neovim (ttyd)
    # NOTE: Unlike other proxy blocks, these do NOT use rewrite to strip the prefix.
    # Both editors are configured with their base path (--proxy-base-path for
    # code-server, --base-path for ttyd) and expect the prefix in the request URI.
    # Do not add a rewrite rule here — it will break asset loading.
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

- [ ] **Step 2: Validate nginx config syntax**

Run: `docker run --rm -v $(pwd)/dashboard/nginx.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine nginx -t 2>&1`
Expected: `syntax is ok` and `test is successful`

- [ ] **Step 3: Commit**

```bash
git add dashboard/nginx.conf
git commit -m "feat(editor): add nginx proxy blocks for embedded editors"
```

---

### Task 5: Environment Variables

**Files:**
- Modify: `.env.example` (insert after Voice Service section, ~line 128)

- [ ] **Step 1: Add editor env vars**

Insert after the Voice Service section in `.env.example` (after line 128):

```bash

# ── Embedded Editor (optional, enable from Dashboard > Settings > Editor) ────
EDITOR_FLAVOR=vscode                          # vscode or neovim
EDITOR_WORKSPACE=${HOME}/.nova/workspace      # Directory mounted into editor
VSCODE_CONFIG_PATH=./data/editor-config/vscode   # VS Code settings/extensions (or ~/.vscode/ to reuse existing)
NEOVIM_CONFIG_PATH=./data/editor-config/neovim   # Neovim config (or ~/.config/nvim/ to reuse existing)
EDITOR_DOTFILES_REPO=                          # Git repo cloned into config dir on startup (optional)
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "feat(editor): add editor env vars to .env.example"
```

---

### Task 6: Dashboard — Editor Page

**Files:**
- Create: `dashboard/src/pages/Editor.tsx`

- [ ] **Step 1: Create the Editor page component**

```tsx
import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Code, ExternalLink, Loader2, MonitorOff, Terminal } from 'lucide-react'

type EditorState = 'detecting' | 'running' | 'starting' | 'stopped'
type EditorFlavor = 'vscode' | 'neovim'

const PROBE_PATHS: Record<EditorFlavor, string> = {
  vscode: '/editor-vscode/',
  neovim: '/editor-neovim/',
}

const FLAVOR_LABELS: Record<EditorFlavor, string> = {
  vscode: 'VS Code',
  neovim: 'Neovim',
}

const FLAVOR_ICONS: Record<EditorFlavor, typeof Code> = {
  vscode: Code,
  neovim: Terminal,
}

async function probeEditor(flavor: EditorFlavor): Promise<boolean> {
  try {
    const res = await fetch(PROBE_PATHS[flavor], { method: 'HEAD', signal: AbortSignal.timeout(3000) })
    return res.ok
  } catch {
    return false
  }
}

async function detectActiveEditor(): Promise<EditorFlavor | null> {
  const [vscode, neovim] = await Promise.all([probeEditor('vscode'), probeEditor('neovim')])
  if (vscode) return 'vscode'
  if (neovim) return 'neovim'
  return null
}

export default function Editor() {
  const [state, setState] = useState<EditorState>('detecting')
  const [activeFlavor, setActiveFlavor] = useState<EditorFlavor | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const detect = useCallback(async () => {
    const flavor = await detectActiveEditor()
    if (flavor) {
      setState('running')
      setActiveFlavor(flavor)
      stopPolling()
    } else if (startedAt && Date.now() - startedAt < 60_000) {
      setState('starting')
    } else {
      setState('stopped')
      stopPolling()
    }
  }, [startedAt, stopPolling])

  useEffect(() => {
    detect()
    pollRef.current = setInterval(detect, 3000)
    return stopPolling
  }, [detect, stopPolling])

  // Allow child components to signal a start action was triggered
  const handleStartTriggered = useCallback(() => {
    setStartedAt(Date.now())
    setState('starting')
    if (!pollRef.current) {
      pollRef.current = setInterval(detect, 3000)
    }
  }, [detect])

  if (state === 'detecting') {
    return (
      <div className="flex items-center justify-center h-full text-stone-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Detecting editor...
      </div>
    )
  }

  if (state === 'starting') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-stone-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin" />
        <p>Editor starting...</p>
        <p className="text-sm text-stone-500">This may take a moment on first launch while the image downloads.</p>
      </div>
    )
  }

  if (state === 'stopped') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-stone-400 gap-4">
        <MonitorOff className="w-12 h-12 text-stone-500" />
        <p className="text-lg">No editor running</p>
        <Link
          to="/settings#connections"
          className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-500 transition-colors"
        >
          Start one in Settings
        </Link>
      </div>
    )
  }

  // Running state — render iframe
  const flavor = activeFlavor!
  const FlavorIcon = FLAVOR_ICONS[flavor]
  const editorUrl = PROBE_PATHS[flavor]

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-stone-900 border-b border-stone-700/50 shrink-0">
        <div className="flex items-center gap-2 text-sm text-stone-300">
          <FlavorIcon className="w-4 h-4" />
          <span>{FLAVOR_LABELS[flavor]}</span>
        </div>
        <a
          href={editorUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-xs text-stone-400 hover:text-stone-200 transition-colors"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          Pop out
        </a>
      </div>

      {/* Editor iframe */}
      <iframe
        src={editorUrl}
        className="flex-1 w-full border-0"
        title={`${FLAVOR_LABELS[flavor]} Editor`}
        allow="clipboard-read; clipboard-write"
      />
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit src/pages/Editor.tsx 2>&1 | head -20`
Expected: No errors (or only pre-existing unrelated errors)

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/Editor.tsx
git commit -m "feat(editor): add embedded editor page with three-state detection"
```

---

### Task 7: Dashboard — Editor Settings Section

**Files:**
- Create: `dashboard/src/pages/settings/EditorSection.tsx`

- [ ] **Step 1: Create the EditorSection component**

```tsx
import { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Code, Terminal, Play, Square, Loader2 } from 'lucide-react'
import { patchEnv, manageComposeProfile, getServiceStatus } from '../../api-recovery'

type EditorFlavor = 'vscode' | 'neovim'

interface EditorConfig {
  flavor: EditorFlavor
  workspace: string
  vscodeConfigPath: string
  neovimConfigPath: string
  dotfilesRepo: string
}

const DEFAULT_CONFIG: EditorConfig = {
  flavor: 'vscode',
  workspace: '~/.nova/workspace',
  vscodeConfigPath: './data/editor-config/vscode',
  neovimConfigPath: './data/editor-config/neovim',
  dotfilesRepo: '',
}

const PROFILE_MAP: Record<EditorFlavor, string> = {
  vscode: 'editor-vscode',
  neovim: 'editor-neovim',
}

export default function EditorSection() {
  const [config, setConfig] = useState<EditorConfig>(DEFAULT_CONFIG)
  const [running, setRunning] = useState<EditorFlavor | null>(null)
  const [checking, setChecking] = useState(true)

  // Check which editor is currently running
  useEffect(() => {
    async function check() {
      setChecking(true)
      try {
        const services = await getServiceStatus()
        const vsRunning = services.some((s: { container_name: string; status: string }) => s.container_name === 'nova-editor-vscode' && s.status === 'running')
        const nvimRunning = services.some((s: { container_name: string; status: string }) => s.container_name === 'nova-editor-neovim' && s.status === 'running')
        setRunning(vsRunning ? 'vscode' : nvimRunning ? 'neovim' : null)
      } catch {
        setRunning(null)
      }
      setChecking(false)
    }
    check()
  }, [])

  const saveMutation = useMutation({
    mutationFn: async (updates: Partial<EditorConfig>) => {
      const envUpdates: Record<string, string> = {}
      if (updates.flavor !== undefined) envUpdates.EDITOR_FLAVOR = updates.flavor
      if (updates.workspace !== undefined) envUpdates.EDITOR_WORKSPACE = updates.workspace
      if (updates.vscodeConfigPath !== undefined) envUpdates.VSCODE_CONFIG_PATH = updates.vscodeConfigPath
      if (updates.neovimConfigPath !== undefined) envUpdates.NEOVIM_CONFIG_PATH = updates.neovimConfigPath
      if (updates.dotfilesRepo !== undefined) envUpdates.EDITOR_DOTFILES_REPO = updates.dotfilesRepo
      if (Object.keys(envUpdates).length > 0) {
        await patchEnv(envUpdates)
      }
    },
  })

  const startMutation = useMutation({
    mutationFn: async (flavor: EditorFlavor) => {
      // Stop current editor if running
      if (running) {
        await manageComposeProfile(PROFILE_MAP[running], 'stop')
      }
      // Save flavor to env
      await patchEnv({ EDITOR_FLAVOR: flavor })
      // Start new editor
      await manageComposeProfile(PROFILE_MAP[flavor], 'start')
      setRunning(flavor)
    },
  })

  const stopMutation = useMutation({
    mutationFn: async () => {
      if (running) {
        await manageComposeProfile(PROFILE_MAP[running], 'stop')
        setRunning(null)
      }
    },
  })

  const isLoading = startMutation.isPending || stopMutation.isPending

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-stone-100">Embedded Editor</h3>
        <p className="text-sm text-stone-400 mt-1">
          Run VS Code or Neovim inside Nova's dashboard. One editor active at a time.
        </p>
      </div>

      {/* Flavor Selection */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-stone-300">Editor Flavor</label>
        <div className="flex gap-3">
          {(['vscode', 'neovim'] as const).map((flavor) => {
            const Icon = flavor === 'vscode' ? Code : Terminal
            const label = flavor === 'vscode' ? 'VS Code' : 'Neovim'
            const isActive = config.flavor === flavor
            return (
              <button
                key={flavor}
                onClick={() => setConfig({ ...config, flavor })}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg border transition-colors ${
                  isActive
                    ? 'border-teal-500 bg-teal-500/10 text-teal-400'
                    : 'border-stone-700 bg-stone-800 text-stone-400 hover:border-stone-600'
                }`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Service Controls */}
      <div className="flex items-center gap-3">
        {running ? (
          <>
            <span className="flex items-center gap-2 text-sm text-emerald-400">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              {running === 'vscode' ? 'VS Code' : 'Neovim'} running
            </span>
            <button
              onClick={() => stopMutation.mutate()}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-red-600/20 text-red-400 rounded-lg hover:bg-red-600/30 disabled:opacity-50 transition-colors"
            >
              {stopMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5" />}
              Stop
            </button>
            {running !== config.flavor && (
              <button
                onClick={() => startMutation.mutate(config.flavor)}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-teal-600 text-white rounded-lg hover:bg-teal-500 disabled:opacity-50 transition-colors"
              >
                {startMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                Switch to {config.flavor === 'vscode' ? 'VS Code' : 'Neovim'}
              </button>
            )}
          </>
        ) : (
          <>
            <span className="flex items-center gap-2 text-sm text-stone-500">
              <span className="w-2 h-2 rounded-full bg-stone-600" />
              {checking ? 'Checking...' : 'Stopped'}
            </span>
            <button
              onClick={() => startMutation.mutate(config.flavor)}
              disabled={isLoading || checking}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-teal-600 text-white rounded-lg hover:bg-teal-500 disabled:opacity-50 transition-colors"
            >
              {startMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              Start {config.flavor === 'vscode' ? 'VS Code' : 'Neovim'}
            </button>
          </>
        )}
      </div>

      {/* Configuration Fields */}
      <div className="space-y-4 border-t border-stone-800 pt-4">
        <div>
          <label className="text-sm font-medium text-stone-300">Workspace Path</label>
          <input
            type="text"
            value={config.workspace}
            onChange={(e) => setConfig({ ...config, workspace: e.target.value })}
            onBlur={() => saveMutation.mutate({ workspace: config.workspace })}
            className="mt-1 w-full px-3 py-2 bg-stone-800 border border-stone-700 rounded-lg text-stone-200 text-sm focus:border-teal-500 focus:outline-none"
            placeholder="~/.nova/workspace"
          />
          <p className="text-xs text-stone-500 mt-1">Directory mounted as /workspace in the editor</p>
        </div>

        <div>
          <label className="text-sm font-medium text-stone-300">
            {config.flavor === 'vscode' ? 'VS Code' : 'Neovim'} Config Path
          </label>
          <input
            type="text"
            value={config.flavor === 'vscode' ? config.vscodeConfigPath : config.neovimConfigPath}
            onChange={(e) =>
              setConfig({
                ...config,
                [config.flavor === 'vscode' ? 'vscodeConfigPath' : 'neovimConfigPath']: e.target.value,
              })
            }
            onBlur={() =>
              saveMutation.mutate(
                config.flavor === 'vscode'
                  ? { vscodeConfigPath: config.vscodeConfigPath }
                  : { neovimConfigPath: config.neovimConfigPath },
              )
            }
            className="mt-1 w-full px-3 py-2 bg-stone-800 border border-stone-700 rounded-lg text-stone-200 text-sm focus:border-teal-500 focus:outline-none"
            placeholder={config.flavor === 'vscode' ? './data/editor-config/vscode' : './data/editor-config/neovim'}
          />
          <p className="text-xs text-stone-500 mt-1">
            {config.flavor === 'vscode'
              ? 'Point at ~/.vscode/ to reuse your existing VS Code config'
              : 'Point at ~/.config/nvim/ to reuse your existing Neovim config'}
          </p>
        </div>

        <div>
          <label className="text-sm font-medium text-stone-300">Dotfiles Repo (optional)</label>
          <input
            type="text"
            value={config.dotfilesRepo}
            onChange={(e) => setConfig({ ...config, dotfilesRepo: e.target.value })}
            onBlur={() => saveMutation.mutate({ dotfilesRepo: config.dotfilesRepo })}
            className="mt-1 w-full px-3 py-2 bg-stone-800 border border-stone-700 rounded-lg text-stone-200 text-sm focus:border-teal-500 focus:outline-none"
            placeholder="https://github.com/you/dotfiles.git"
          />
          <p className="text-xs text-stone-500 mt-1">Cloned into the config directory on editor startup</p>
        </div>
      </div>

      {/* Error display */}
      {(startMutation.error || stopMutation.error || saveMutation.error) && (
        <p className="text-sm text-red-400">
          {(startMutation.error || stopMutation.error || saveMutation.error)?.message || 'An error occurred'}
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | grep -i "EditorSection" | head -10`
Expected: No errors referencing EditorSection

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/settings/EditorSection.tsx
git commit -m "feat(editor): add editor settings section component"
```

---

### Task 8: Dashboard — Route Wiring and Navigation

**Files:**
- Modify: `dashboard/src/App.tsx:167-200`
- Modify: `dashboard/src/components/layout/Sidebar.tsx:59-66`
- Modify: `dashboard/src/pages/Settings.tsx:126-134`

- [ ] **Step 1: Add Editor lazy import to App.tsx**

At the top of `App.tsx` where other lazy imports are defined, add:

```tsx
const Editor = lazy(() => import('./pages/Editor'))
```

Also add `Navigate` to the react-router-dom import if not already there.

- [ ] **Step 2: Add /editor route and rename /editors**

In `App.tsx`, in the routes section:

1. Add the new `/editor` route (full-width, like `/chat` and `/brain`):
```tsx
<Route path="/editor" element={<MobileGuard><AppLayout fullWidth><ErrorBoundary><Suspense fallback={null}><Editor /></Suspense></ErrorBoundary></AppLayout></MobileGuard>} />
```

2. Rename the existing `/editors` route to `/ide-connections`:
```tsx
<Route path="/ide-connections" element={<MobileGuard><AppLayout><ErrorBoundary><Suspense fallback={null}><Editors /></Suspense></ErrorBoundary></AppLayout></MobileGuard>} />
```

3. Add a redirect from the old `/editors` path in the redirects section:
```tsx
<Route path="/editors" element={<Navigate to="/ide-connections" replace />} />
```

- [ ] **Step 3: Update sidebar navigation**

In `dashboard/src/components/layout/Sidebar.tsx`, update the Infrastructure section (lines 60-66):

```tsx
{
  label: 'Infrastructure',
  items: [
    { to: '/pods', label: 'Pods', icon: Boxes, minRole: 'admin' },
    { to: '/models', label: 'Models', icon: Monitor, minRole: 'member' },
    { to: '/editor', label: 'Editor', icon: Code, minRole: 'member' },
    { to: '/ide-connections', label: 'IDE Connections', icon: Plug, minRole: 'member' },
    { to: '/integrations', label: 'Integrations', icon: Plug, minRole: 'admin' },
  ],
},
```

Note: If `Plug` is already used for Integrations, use a different icon for IDE Connections — `Cable` or `MonitorSmartphone` from Lucide.

- [ ] **Step 4: Add Editor section to Settings NAV_GROUPS**

In `dashboard/src/pages/Settings.tsx`, add an `editor` item to the `connections` group (lines 126-134):

```tsx
{
  id: 'connections',
  label: 'Connections',
  icon: Globe,
  items: [
    { id: 'remote-access', label: 'Remote Access', icon: Globe },
    { id: 'chat-integrations', label: 'Chat Integrations', icon: MessageSquare },
    { id: 'editor', label: 'Editor', icon: Code },
    { id: 'notifications', label: 'Notifications', icon: Bell },
  ],
},
```

Add the `Code` icon to the Lucide import at the top of Settings.tsx.

- [ ] **Step 5: Render EditorSection in Settings**

In `Settings.tsx`, add the import and render block. Find where other sections are rendered (search for `show('chat-integrations')` as a pattern reference) and add:

```tsx
{show('editor') && <EditorSection />}
```

Import at the top:
```tsx
import EditorSection from './settings/EditorSection'
```

- [ ] **Step 6: Verify the dashboard builds**

Run: `cd dashboard && npm run build 2>&1 | tail -5`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/App.tsx dashboard/src/components/layout/Sidebar.tsx dashboard/src/pages/Settings.tsx
git commit -m "feat(editor): wire editor route, sidebar nav, and settings section"
```

---

### Task 9: End-to-End Smoke Test

- [ ] **Step 1: Rebuild and start services**

Run: `make build && docker compose up -d`
Expected: All core services start. Editor services should NOT be running (they have profiles).

- [ ] **Step 2: Start VS Code editor via profile**

Run: `docker compose --profile editor-vscode up -d editor-vscode`
Expected: editor-vscode container starts and passes healthcheck

Run: `docker compose ps editor-vscode`
Expected: Status shows "healthy"

- [ ] **Step 3: Verify nginx proxy**

Run: `curl -sf -o /dev/null -w '%{http_code}' http://localhost:3000/editor-vscode/`
Expected: `200`

- [ ] **Step 4: Verify neovim editor**

Stop vscode: `docker compose stop editor-vscode`
Start neovim: `docker compose --profile editor-neovim up -d editor-neovim`

Run: `curl -sf -o /dev/null -w '%{http_code}' http://localhost:3000/editor-neovim/`
Expected: `200`

- [ ] **Step 5: Verify dashboard Editor page loads**

Open `http://localhost:3000/editor` in a browser.
Expected: Neovim editor renders in an iframe with the top bar showing "Neovim" and a pop-out button.

- [ ] **Step 6: Verify Settings > Editor section**

Open `http://localhost:3000/settings#connections` and click "Editor".
Expected: Editor section shows flavor selector, status badge (running), workspace path, config path, and dotfiles fields.

- [ ] **Step 7: Verify /editors redirect**

Open `http://localhost:3000/editors` in a browser.
Expected: Redirects to `/ide-connections`.

- [ ] **Step 8: Cleanup and commit**

Stop editor: `docker compose stop editor-neovim`

```bash
git add -A
git commit -m "test: verify embedded editor end-to-end smoke test passes"
```

(Only commit if any test fixtures or minor adjustments were needed during smoke testing.)
