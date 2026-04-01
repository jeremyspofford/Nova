# IDE Integration Onboarding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dashboard page and onboarding card that lets users generate editor configs, test connections, and monitor which editors are connected to Nova.

**Architecture:** New `/editors` dashboard page with tabbed config generators per editor. LLM Gateway tracks which editors are hitting `/v1/chat/completions` via per-editor Redis keys with 5-minute TTL. A new `GET /v1/editor-connections` endpoint exposes this state. The onboarding wizard's Ready screen gains a "Connect Your Editor" card.

**Tech Stack:** React + TypeScript + Tailwind (dashboard), FastAPI + redis.asyncio (gateway), TanStack Query (polling), existing `useTabHash` hook, existing `apiFetch`/`getKeys`/`createKey`/`revokeKey` API helpers.

**Spec:** `docs/superpowers/specs/2026-04-01-ide-integration-onboarding-design.md`

---

## File Map

### New Files

| File | Responsibility |
|---|---|
| `dashboard/src/pages/Editors.tsx` | Main page: connection monitor, editor tabs, config generation, test connection |
| `dashboard/src/pages/editors/editorConfigs.ts` | Editor metadata + config template functions (pure data, no React) |
| `llm-gateway/app/editor_tracker.py` | Redis-backed connection tracking: record, query, close |

### Modified Files

| File | Change |
|---|---|
| `dashboard/src/App.tsx` | Add `/editors` route + lazy import |
| `dashboard/src/components/layout/Sidebar.tsx` | Add "Editors" nav item with `Code` icon in Infrastructure section |
| `dashboard/src/components/layout/MobileNav.tsx` | Add "Editors" nav item in Infrastructure section (mirrors sidebar) |
| `dashboard/src/pages/onboarding/steps/Ready.tsx` | Add "Connect Your Editor" card alongside "Start Chatting" |
| `llm-gateway/app/openai_router.py` | Call `record_editor_connection()` after successful completions |
| `llm-gateway/app/main.py` | Import and close editor tracker Redis in lifespan shutdown |

---

## Task 1: Editor Config Templates (Pure Data)

**Files:**
- Create: `dashboard/src/pages/editors/editorConfigs.ts`

This is the data layer — editor metadata and config generators with zero React dependencies.

- [ ] **Step 1: Create the editor config module**

```typescript
// dashboard/src/pages/editors/editorConfigs.ts

export type EditorSlug = 'continue' | 'cline' | 'cursor' | 'aider' | 'windsurf' | 'generic'

export interface EditorMeta {
  slug: EditorSlug
  name: string
  description: string
  configFormat: 'json' | 'cli' | 'instructions' | 'curl'
}

export const EDITORS: EditorMeta[] = [
  { slug: 'continue', name: 'Continue.dev', description: 'VS Code & JetBrains', configFormat: 'json' },
  { slug: 'cline', name: 'Cline', description: 'VS Code — agentic coding', configFormat: 'json' },
  { slug: 'cursor', name: 'Cursor', description: 'AI-native editor', configFormat: 'instructions' },
  { slug: 'aider', name: 'Aider', description: 'Terminal', configFormat: 'cli' },
  { slug: 'windsurf', name: 'Windsurf', description: 'Codium editor', configFormat: 'json' },
  { slug: 'generic', name: 'Other / Generic', description: 'Any OpenAI-compatible tool', configFormat: 'curl' },
]

export const EDITOR_SLUGS = EDITORS.map(e => e.slug) as readonly EditorSlug[]

/**
 * Generate the config snippet a user pastes into their editor.
 */
export function generateConfig(
  slug: EditorSlug,
  endpoint: string,
  model: string,
  apiKey: string,
): string {
  switch (slug) {
    case 'continue':
      return JSON.stringify({
        title: `Nova (${model.split('/').pop()})`,
        provider: 'openai',
        model,
        apiBase: endpoint,
        apiKey,
      }, null, 2)

    case 'cline':
      return JSON.stringify({
        apiProvider: 'openai-compatible',
        openaiBaseUrl: endpoint,
        openaiModelId: model,
        openaiApiKey: apiKey,
      }, null, 2)

    case 'cursor':
      // Cursor uses a UI form, not a config file
      return [
        `Base URL:  ${endpoint}`,
        `API Key:   ${apiKey}`,
        `Model:     ${model}`,
      ].join('\n')

    case 'aider':
      return `aider \\
  --openai-api-base ${endpoint} \\
  --openai-api-key ${apiKey} \\
  --model ${model}`

    case 'windsurf':
      return JSON.stringify({
        title: `Nova (${model.split('/').pop()})`,
        provider: 'openai',
        model,
        apiBase: endpoint,
        apiKey,
      }, null, 2)

    case 'generic':
      return `curl ${endpoint}/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey}" \\
  -d '{
    "model": "${model}",
    "messages": [{"role": "user", "content": "Hello from Nova"}]
  }'`
  }
}

/**
 * Editor-specific paste instructions (step-by-step).
 */
export function getPasteInstructions(slug: EditorSlug): string[] {
  switch (slug) {
    case 'continue':
      return [
        'Open VS Code or JetBrains',
        'Cmd+Shift+P (or Ctrl+Shift+P) → "Continue: Open config.json"',
        'Add the JSON above to the "models" array',
        'Save the file — the model appears in the Continue sidebar',
      ]
    case 'cline':
      return [
        'Open VS Code',
        'Click the Cline icon in the sidebar',
        'Open Settings (gear icon)',
        'Select "OpenAI Compatible" as the API provider',
        'Paste the Base URL, API Key, and Model ID from the config above',
      ]
    case 'cursor':
      return [
        'Open Cursor → Settings → Models',
        'Click "Add model"',
        'Enter the Base URL, API Key, and Model name shown above',
        'Click Save',
      ]
    case 'aider':
      return [
        'Open a terminal in your project directory',
        'Run the command above (or add flags to your .aider.conf.yml)',
      ]
    case 'windsurf':
      return [
        'Open Windsurf → Settings',
        'Navigate to AI Provider configuration',
        'Add a new OpenAI-compatible provider',
        'Paste the JSON config above',
      ]
    case 'generic':
      return [
        'Use the endpoint URL and API key in any OpenAI-compatible tool',
        'The curl example above shows the exact request format',
      ]
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: no errors related to `editorConfigs.ts`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/editors/editorConfigs.ts
git commit -m "feat(dashboard): add editor config templates for IDE integration"
```

---

## Task 2: Gateway Editor Tracking (Backend)

**Files:**
- Create: `llm-gateway/app/editor_tracker.py`
- Modify: `llm-gateway/app/openai_router.py`
- Modify: `llm-gateway/app/main.py`

- [ ] **Step 1: Create the editor tracker module**

```python
# llm-gateway/app/editor_tracker.py
"""
Track which editors are connected to the Nova LLM Gateway.

Stores per-editor connection state in Redis with 5-minute TTL.
Detection: primary via API key name (editor-{slug}), fallback via User-Agent.
"""
from __future__ import annotations

import json
import logging
import time

import redis.asyncio as aioredis

from app.config import settings

log = logging.getLogger(__name__)

UA_PATTERNS: dict[str, str] = {
    "continue": "continue",
    "cline": "cline",
    "cursor": "cursor",
    "aider": "aider",
    "windsurf": "windsurf",
}

KNOWN_EDITORS = ["continue", "cline", "cursor", "aider", "windsurf", "generic"]
_KEY_PREFIX = "nova:editor:connection:"
_TTL = 300  # 5 minutes

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def detect_editor_slug(editor_hint: str | None, user_agent: str | None) -> str | None:
    """Identify the editor from an explicit hint header or User-Agent.

    Detection methods (in priority order):
    1. X-Nova-Editor header — set by the dashboard's test connection button
    2. User-Agent sniffing — works for Continue, Cline, Aider, and some others

    Returns an editor slug or None if unrecognized.
    """
    # Primary: explicit editor hint (from dashboard test or custom header)
    if editor_hint:
        hint_lower = editor_hint.lower().strip()
        if hint_lower in KNOWN_EDITORS:
            return hint_lower
        # Also accept "editor-continue" format
        if hint_lower.startswith("editor-"):
            slug = hint_lower.removeprefix("editor-")
            if slug in KNOWN_EDITORS:
                return slug

    # Fallback: User-Agent sniffing
    if user_agent:
        ua_lower = user_agent.lower()
        for slug, pattern in UA_PATTERNS.items():
            if pattern in ua_lower:
                return slug

    return None


async def record_connection(slug: str, user_agent: str | None) -> None:
    """Record that an editor just made a successful request."""
    try:
        r = await _get_redis()
        key = f"{_KEY_PREFIX}{slug}"

        # Read existing to increment counter
        raw = await r.get(key)
        count = 1
        if raw:
            try:
                prev = json.loads(raw)
                count = prev.get("request_count", 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

        value = json.dumps({
            "last_seen": time.time(),
            "user_agent": user_agent or "",
            "request_count": count,
        })
        await r.set(key, value, ex=_TTL)
    except Exception as e:
        # Non-critical — don't break completions
        log.debug("Editor tracking write failed: %s", e)


async def get_connections() -> dict:
    """Return connection state for all known editors."""
    r = await _get_redis()
    now = time.time()
    connections: dict[str, dict] = {}

    for slug in KNOWN_EDITORS:
        key = f"{_KEY_PREFIX}{slug}"
        raw = await r.get(key)
        if raw:
            try:
                data = json.loads(raw)
                last_seen = data.get("last_seen", 0)
                age = now - last_seen
                if age < 60:
                    status = "connected"
                elif age < 300:
                    status = "idle"
                else:
                    status = "disconnected"
                connections[f"editor-{slug}"] = {
                    "editor": slug,
                    "last_seen": data.get("last_seen"),
                    "request_count": data.get("request_count", 0),
                    "status": status,
                }
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            connections[f"editor-{slug}"] = {
                "editor": slug,
                "last_seen": None,
                "request_count": 0,
                "status": "never",
            }

    return connections
```

- [ ] **Step 2: Add the `/v1/editor-connections` endpoint and tracking call to the openai router**

In `llm-gateway/app/openai_router.py`, add the tracking call after successful completions and the new endpoint.

Add imports at top of file (after existing imports):
```python
from app.config import settings
from app.editor_tracker import detect_editor_slug, record_connection, get_connections
```

Add tracking after the non-streaming response (after line 121, `return nova_response_to_oai(...)`):

Replace the non-streaming branch with tracking:
```python
    else:
        response = await provider.complete(nova_req)
        log.info(
            "openai-compat complete model=%s in=%d out=%d cost=$%.6f",
            req.model,
            response.input_tokens,
            response.output_tokens,
            response.cost_usd or 0,
        )
        # Track editor connection (non-critical, best-effort)
        _track_editor(raw_request)
        return nova_response_to_oai(response, request_model=req.model)
```

For streaming, add tracking call inside `generate()` just before `yield b"data: [DONE]\n\n"` (the success path at line 100, not the error path). Use fire-and-forget to avoid blocking the final SSE chunk:
```python
                # Track editor connection after successful stream (non-blocking)
                _track_editor(raw_request)
                yield b"data: [DONE]\n\n"
```

Add the helper function and endpoint after the `list_models_oai` function:

```python
def _track_editor(request: Request) -> None:
    """Fire-and-forget editor tracking. Runs in background to not slow responses."""
    import asyncio
    asyncio.create_task(_record_editor(request))


async def _record_editor(request: Request) -> None:
    """Detect and record editor connection from request headers."""
    try:
        user_agent = request.headers.get("user-agent")
        # Check for editor hint header (set by dashboard test connection)
        editor_hint = request.headers.get("x-nova-editor")
        slug = detect_editor_slug(editor_hint, user_agent)
        if slug:
            await record_connection(slug, user_agent)
    except Exception:
        pass  # Non-critical


@openai_router.get("/editor-connections")
async def editor_connections():
    """Return connection state for all known editors."""
    connections = await get_connections()
    endpoint = settings.gateway_public_url
    auth_required = settings.require_auth
    return {
        "connections": connections,
        "endpoint": endpoint,
        "auth_required": auth_required,
    }
```

- [ ] **Step 3: Add config fields and lifespan cleanup to gateway**

In `llm-gateway/app/config.py`, add after `log_level` field (line 152):
```python
    gateway_public_url: str = "http://localhost:8001/v1"
    require_auth: bool = False
```

In `llm-gateway/app/main.py`, add to the lifespan shutdown (after line 54, `await close_response_cache()`):
```python
    from app.editor_tracker import close as close_editor_tracker
    await close_editor_tracker()
```

- [ ] **Step 4: Verify gateway starts cleanly**

Run: `cd llm-gateway && python -c "from app.editor_tracker import detect_editor_slug, record_connection, get_connections, close; print('imports OK')"`
Expected: `imports OK`

- [ ] **Step 5: Commit**

```bash
git add llm-gateway/app/editor_tracker.py llm-gateway/app/openai_router.py llm-gateway/app/main.py llm-gateway/app/config.py
git commit -m "feat(llm-gateway): add editor connection tracking and /v1/editor-connections endpoint"
```

---

## Task 3: Editors Dashboard Page

**Files:**
- Create: `dashboard/src/pages/Editors.tsx`

This is the main page with all three zones: connection monitor, editor tabs, and config content.

- [ ] **Step 1: Create the Editors page**

```tsx
// dashboard/src/pages/Editors.tsx
import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Code, Copy, Check, RefreshCw, Zap, AlertCircle } from 'lucide-react'
import clsx from 'clsx'
import { apiFetch, getKeys, createKey, revokeKey, getModels } from '../api'
import { getAuthHeaders } from '../api'
import { useAuth } from '../stores/auth-store'
import { hasMinRole } from '../lib/roles'
import { useTabHash } from '../hooks/useTabHash'
import { Button } from '../components/ui'
import {
  EDITORS,
  EDITOR_SLUGS,
  generateConfig,
  getPasteInstructions,
  type EditorSlug,
} from './editors/editorConfigs'

// ── Types ────────────────────────────────────────────────────────────────────

interface EditorConnection {
  editor: string
  last_seen: number | null
  request_count: number
  status: 'connected' | 'idle' | 'disconnected' | 'never'
}

interface ConnectionsResponse {
  connections: Record<string, EditorConnection>
  endpoint: string
  auth_required: boolean
}

// ── Connection Monitor (Zone 1) ──────────────────────────────────────────────

function ConnectionMonitor({ data }: { data: ConnectionsResponse | undefined }) {
  const [copied, setCopied] = useState(false)
  const endpoint = data?.endpoint ?? 'http://localhost:8001/v1'

  const copyEndpoint = () => {
    navigator.clipboard.writeText(endpoint)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const statusDot = (status: string) => {
    if (status === 'connected') return 'bg-success'
    if (status === 'idle') return 'bg-warning'
    return 'bg-neutral-500'
  }

  const formatLastSeen = (ts: number | null) => {
    if (!ts) return null
    const ago = Math.round((Date.now() / 1000) - ts)
    if (ago < 60) return `${ago}s ago`
    if (ago < 3600) return `${Math.round(ago / 60)}m ago`
    return `${Math.round(ago / 3600)}h ago`
  }

  return (
    <div className="flex items-center justify-between gap-4 p-4 border-b border-border-subtle">
      <div className="flex-1">
        <div className="text-micro font-semibold uppercase tracking-wider text-content-tertiary mb-2">
          Connected Editors
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {data && Object.values(data.connections).map(conn => (
            <div key={conn.editor} className="flex items-center gap-1.5 text-compact">
              <div className={clsx('w-1.5 h-1.5 rounded-full', statusDot(conn.status))} />
              <span className={clsx(
                conn.status === 'connected' ? 'text-content-primary' : 'text-content-tertiary',
              )}>
                {EDITORS.find(e => e.slug === conn.editor)?.name ?? conn.editor}
              </span>
              {conn.status === 'connected' && conn.last_seen && (
                <span className="text-content-tertiary text-micro">{formatLastSeen(conn.last_seen)}</span>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-2 text-compact text-content-secondary shrink-0">
        <span className="font-mono text-micro">{endpoint}</span>
        <button
          onClick={copyEndpoint}
          className="p-1 rounded hover:bg-surface-elevated transition-colors"
          title="Copy endpoint URL"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  )
}

// ── Config Panel (Zone 3) ────────────────────────────────────────────────────

function ConfigPanel({
  slug,
  endpoint,
  authRequired,
}: {
  slug: EditorSlug
  endpoint: string
  authRequired: boolean
}) {
  const { user, authConfig } = useAuth()
  const userRole = (user?.role ?? (authConfig?.trusted_network ? 'owner' : 'guest')) as string
  const isAdmin = hasMinRole(userRole as any, 'admin')

  const [copied, setCopied] = useState(false)
  const [selectedModel, setSelectedModel] = useState('')
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle')
  const [testError, setTestError] = useState('')
  const [editorKey, setEditorKey] = useState<string | null>(null)
  const [editorKeyId, setEditorKeyId] = useState<string | null>(null)

  // Fetch available models
  const { data: modelsData } = useQuery({
    queryKey: ['oai-models'],
    queryFn: getModels,
    staleTime: 30_000,
  })
  const models = modelsData?.data ?? []

  // Set default model on load
  useEffect(() => {
    if (models.length > 0 && !selectedModel) {
      setSelectedModel(models[0].id)
    }
  }, [models, selectedModel])

  // Fetch/create editor API key
  const { data: keys, refetch: refetchKeys } = useQuery({
    queryKey: ['api-keys'],
    queryFn: getKeys,
    enabled: authRequired && isAdmin,
    staleTime: 10_000,
  })

  // Find existing key for this editor
  const existingKey = keys?.find(k => k.name === `editor-${slug}`)

  // Determine the API key value to show in config
  const apiKeyDisplay = authRequired
    ? (editorKey ?? existingKey?.key_prefix ?? 'sk-nova-...')
    : 'unused'

  // Create key for this editor
  const createEditorKey = useMutation({
    mutationFn: async () => {
      if (existingKey) return null // Already exists
      const result = await createKey(`editor-${slug}`, 120)
      setEditorKey(result.raw_key)
      setEditorKeyId(result.id)
      return result
    },
    onSuccess: () => refetchKeys(),
  })

  // Regenerate key (revoke + recreate)
  const regenerateKey = useMutation({
    mutationFn: async () => {
      const keyToRevoke = editorKeyId ?? existingKey?.id
      if (keyToRevoke) {
        await revokeKey(keyToRevoke)
      }
      const result = await createKey(`editor-${slug}`, 120)
      setEditorKey(result.raw_key)
      setEditorKeyId(result.id)
      return result
    },
    onSuccess: () => refetchKeys(),
  })

  // Auto-create key on tab visit (if auth required, admin, and no key exists)
  const [keyCreationAttempted, setKeyCreationAttempted] = useState(false)
  useEffect(() => {
    if (authRequired && isAdmin && !existingKey && !editorKey && !keyCreationAttempted) {
      setKeyCreationAttempted(true)
      createEditorKey.mutate()
    }
  }, [authRequired, isAdmin, existingKey, editorKey, keyCreationAttempted])

  const config = generateConfig(slug, endpoint, selectedModel || 'your-model-id', apiKeyDisplay)
  const instructions = getPasteInstructions(slug)

  const copyConfig = () => {
    navigator.clipboard.writeText(config)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const testConnection = async () => {
    setTestStatus('testing')
    setTestError('')
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Nova-Editor': slug, // Tells the gateway which editor this is
      }
      if (authRequired && apiKeyDisplay !== 'sk-nova-...') {
        headers['Authorization'] = `Bearer ${apiKeyDisplay}`
      }
      const resp = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          model: selectedModel,
          messages: [{ role: 'user', content: 'ping' }],
          max_tokens: 1,
        }),
      })
      if (resp.ok) {
        setTestStatus('success')
      } else if (resp.status === 401 || resp.status === 403) {
        setTestStatus('error')
        setTestError('API key is invalid or revoked. Click Regenerate Key.')
      } else {
        const text = await resp.text().catch(() => '')
        setTestStatus('error')
        setTestError(text || `Gateway returned ${resp.status}`)
      }
    } catch {
      setTestStatus('error')
      setTestError('LLM Gateway is not responding. Check service status.')
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Non-admin warning */}
      {authRequired && !isAdmin && (
        <div className="flex items-start gap-2 p-3 rounded-md bg-warning/10 border border-warning/20 text-compact text-warning">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>Ask an admin to create an API key for you, or create one from Settings &gt; Keys.</span>
        </div>
      )}

      {/* Model selector */}
      <div>
        <label className="text-micro font-semibold uppercase tracking-wider text-content-tertiary mb-1.5 block">
          Step 1: Pick a model
        </label>
        <select
          value={selectedModel}
          onChange={e => setSelectedModel(e.target.value)}
          className="w-full max-w-sm rounded-md border border-border-subtle bg-surface-root px-3 py-2 text-compact text-content-primary focus:outline-none focus:ring-1 focus:ring-accent"
        >
          {models.map(m => (
            <option key={m.id} value={m.id}>{m.id}</option>
          ))}
        </select>
      </div>

      {/* Config block */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-micro font-semibold uppercase tracking-wider text-content-tertiary">
            Step 2: Copy this config
          </label>
          <button
            onClick={copyConfig}
            className="flex items-center gap-1 text-micro text-accent hover:text-accent-hover transition-colors"
          >
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
        <pre className="p-4 rounded-md bg-surface-root border border-border-subtle text-compact font-mono overflow-x-auto text-content-secondary">
          {config}
        </pre>
        {authRequired && isAdmin && (editorKey || existingKey) && (
          <div className="mt-2 flex items-center gap-2">
            <button
              onClick={() => regenerateKey.mutate()}
              disabled={regenerateKey.isPending}
              className="flex items-center gap-1 text-micro text-content-tertiary hover:text-content-primary transition-colors"
            >
              <RefreshCw className={clsx('w-3 h-3', regenerateKey.isPending && 'animate-spin')} />
              Regenerate Key
            </button>
            {regenerateKey.isSuccess && (
              <span className="text-micro text-warning">Key regenerated — update your editor config.</span>
            )}
          </div>
        )}
      </div>

      {/* Paste instructions */}
      <div>
        <label className="text-micro font-semibold uppercase tracking-wider text-content-tertiary mb-1.5 block">
          Step 3: Paste in your editor
        </label>
        <ol className="space-y-1 text-compact text-content-secondary list-decimal list-inside">
          {instructions.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      </div>

      {/* Test connection */}
      <div className="flex items-center gap-3">
        <Button
          size="sm"
          icon={<Zap className="w-3.5 h-3.5" />}
          onClick={testConnection}
          disabled={testStatus === 'testing' || !selectedModel}
        >
          {testStatus === 'testing' ? 'Testing...' : 'Test Connection'}
        </Button>
        {testStatus === 'success' && (
          <span className="flex items-center gap-1 text-compact text-success">
            <Check className="w-4 h-4" />
            Connected! Nova received the request using {selectedModel}.
          </span>
        )}
        {testStatus === 'error' && (
          <span className="flex items-center gap-1 text-compact text-danger">
            <AlertCircle className="w-4 h-4" />
            {testError}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function Editors() {
  const [tab, setTab] = useTabHash<EditorSlug>('continue', EDITOR_SLUGS)

  const { data: connections } = useQuery<ConnectionsResponse>({
    queryKey: ['editor-connections'],
    queryFn: () => apiFetch('/v1/editor-connections'),
    refetchInterval: 5_000,
  })

  const endpoint = connections?.endpoint ?? 'http://localhost:8001/v1'
  const authRequired = connections?.auth_required ?? false

  return (
    <div className="mx-auto max-w-4xl space-y-0">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg bg-accent-dim">
          <Code className="w-5 h-5 text-accent" />
        </div>
        <div>
          <h1 className="text-h3 text-content-primary">Connect Your Editor</h1>
          <p className="text-compact text-content-secondary">
            Use Nova as your AI backend in any editor
          </p>
        </div>
      </div>

      <div className="bg-surface-card rounded-lg border border-border-subtle glass-card dark:border-white/[0.08] overflow-hidden">
        {/* Zone 1: Connection monitor */}
        <ConnectionMonitor data={connections} />

        {/* Zone 2: Editor tabs */}
        <div className="flex border-b border-border-subtle overflow-x-auto">
          {EDITORS.map(editor => (
            <button
              key={editor.slug}
              onClick={() => setTab(editor.slug)}
              className={clsx(
                'px-4 py-3 text-compact font-medium whitespace-nowrap transition-colors border-b-2 -mb-px',
                tab === editor.slug
                  ? 'border-accent text-accent'
                  : 'border-transparent text-content-tertiary hover:text-content-secondary',
              )}
            >
              {editor.name}
            </button>
          ))}
        </div>

        {/* Zone 3: Config content */}
        <ConfigPanel
          key={tab}
          slug={tab}
          endpoint={endpoint}
          authRequired={authRequired}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: no errors related to `Editors.tsx`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/Editors.tsx
git commit -m "feat(dashboard): add Editors page with config generation, test, and monitor"
```

---

## Task 4: Wire Up Routes, Sidebar, and Mobile Nav

**Files:**
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/components/layout/Sidebar.tsx`
- Modify: `dashboard/src/components/layout/MobileNav.tsx`

- [ ] **Step 1: Add route in App.tsx**

Add import near the top (after line 31, the `ComponentGallery` import):
```typescript
const Editors = lazy(() => import('./pages/Editors'))
```

Add the `lazy` import to the existing React import on line 1:
```typescript
import { useState, useCallback, useEffect, lazy, Suspense } from 'react'
```

Add the route after the `/models` route (after line 175):
```typescript
        <Route path="/editors" element={<AppLayout><ErrorBoundary><Suspense fallback={null}><Editors /></Suspense></ErrorBoundary></AppLayout>} />
```

- [ ] **Step 2: Add nav item in Sidebar.tsx**

Add `Code` to the Lucide imports on line 4 (it's already a named export from lucide-react):
```typescript
import {
  MessageSquare,
  ListTodo,
  AlertTriangle,
  Target,
  Globe,
  Brain,
  Boxes,
  Monitor,
  Code,
  Plug,
  BarChart3,
  Settings,
  ChevronsLeft,
  ChevronsRight,
  ChevronDown,
  Users,
} from 'lucide-react'
```

Add the Editors nav item in the Infrastructure section (after the Models item, before the Integrations item — line 62):
```typescript
      { to: '/editors', label: 'Editors', icon: Code, minRole: 'member' },
```

- [ ] **Step 3: Add nav item in MobileNav.tsx**

Add `Code` to the Lucide imports:
```typescript
import {
  MessageSquare,
  ListTodo,
  Target,
  Brain,
  Ellipsis,
  X,
  Globe,
  Boxes,
  Monitor,
  Code,
  Plug,
  BarChart3,
  Settings,
  HeartPulse,
  Users,
} from 'lucide-react'
```

Add in the Infrastructure section of `moreItems` (after Models, before Integrations — line 50):
```typescript
      { to: '/editors', label: 'Editors', icon: Code, minRole: 'member' },
```

- [ ] **Step 4: Verify build compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/App.tsx dashboard/src/components/layout/Sidebar.tsx dashboard/src/components/layout/MobileNav.tsx
git commit -m "feat(dashboard): add Editors route and nav items in sidebar and mobile nav"
```

---

## Task 5: Onboarding Ready Screen Card

**Files:**
- Modify: `dashboard/src/pages/onboarding/steps/Ready.tsx`

- [ ] **Step 1: Add the "Connect Your Editor" card**

Replace the entire content of `Ready.tsx`:

```tsx
import { Check, MessageSquare, Settings, Code } from 'lucide-react'
import { Button } from '../../../components/ui'

interface Props {
  backend: string
  model: string
  onFinish: () => void
}

export function Ready({ backend, model, onFinish }: Props) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="w-16 h-16 rounded-full bg-success flex items-center justify-center mb-6">
        <Check className="w-8 h-8 text-white" />
      </div>
      <h2 className="text-h3 text-content-primary mb-2">
        Nova is Ready
      </h2>
      <p className="text-compact text-content-secondary mb-2">
        {backend === 'cloud'
          ? 'Cloud providers are configured and ready to go.'
          : (
            <>
              <span className="font-medium text-content-primary">{model}</span>
              {' '}is running via{' '}
              <span className="font-medium text-content-primary">{backend}</span>.
            </>
          )
        }
      </p>
      <p className="text-caption text-content-tertiary mb-8 flex items-center gap-1">
        <Settings className="w-3 h-3" />
        You can change models and backends anytime in Settings.
      </p>
      <div className="flex gap-3">
        <Button
          size="lg"
          icon={<MessageSquare className="w-4 h-4" />}
          onClick={onFinish}
        >
          Start Chatting
        </Button>
        <Button
          size="lg"
          variant="secondary"
          icon={<Code className="w-4 h-4" />}
          onClick={() => { window.location.href = '/editors' }}
        >
          Connect Your Editor
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify build compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/onboarding/steps/Ready.tsx
git commit -m "feat(dashboard): add Connect Your Editor card to onboarding Ready screen"
```

---

## Task 6: Build Verification & Smoke Test

- [ ] **Step 1: Full TypeScript build check**

Run: `cd dashboard && npm run build 2>&1 | tail -10`
Expected: build succeeds with no errors

- [ ] **Step 2: Verify gateway imports**

Run: `cd llm-gateway && python -c "from app.editor_tracker import detect_editor_slug, record_connection, get_connections, close; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify editor tracker detection logic**

Run:
```bash
cd llm-gateway && python -c "
from app.editor_tracker import detect_editor_slug
# Explicit editor hint (from X-Nova-Editor header)
assert detect_editor_slug('continue', None) == 'continue'
assert detect_editor_slug('editor-cline', None) == 'cline'
# User-Agent fallback
assert detect_editor_slug(None, 'Mozilla/5.0 Continue/1.0') == 'continue'
assert detect_editor_slug(None, 'some-unknown-agent') is None
# No detection at all
assert detect_editor_slug(None, None) is None
print('All detection tests passed')
"
```
Expected: `All detection tests passed`

- [ ] **Step 4: Commit any fixes if needed, then final commit**

```bash
git add -A
git status
# Only commit if there are changes
git diff --cached --quiet || git commit -m "fix: address build issues from IDE integration feature"
```
