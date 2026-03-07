# Unified AI Identity System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Nova's name, persona, and greeting configurable from Settings with changes flowing through to the system prompt, toolbar, and chat UI — and remove the Overview page.

**Architecture:** `platform_config` in Postgres is the single source of truth for identity (`nova.name`, `nova.persona`, `nova.greeting`). The orchestrator loads these at prompt-build time and exposes a public `/api/v1/identity` endpoint. The dashboard reads this endpoint for NavBar and Chat. Overview page is removed; Chat becomes the `/` route. System Services panel moves to Settings.

**Tech Stack:** Python/FastAPI (orchestrator, chat-api), React/TypeScript/TanStack Query (dashboard), PostgreSQL (platform_config table)

---

### Task 1: Backend — Identity endpoint + prompt assembly

**Files:**
- Modify: `orchestrator/app/agents/runner.py:264-345`
- Modify: `orchestrator/app/router.py` (add endpoint)
- Modify: `orchestrator/app/config.py:12-15`
- Modify: `chat-api/app/session.py:47-58`
- Create: `orchestrator/app/migrations/013_identity_greeting.sql`

**Step 1: Create migration to update greeting default with `{name}` placeholder**

Create `orchestrator/app/migrations/013_identity_greeting.sql`:

```sql
-- Migration 013: Update default greeting to use {name} placeholder
-- Existing custom greetings are left untouched.

UPDATE platform_config
SET value = '"Hello! I''m {name}. I have access to your workspace, can run shell commands, read and write files, and remember our previous conversations. What would you like to work on?"'
WHERE key = 'nova.greeting'
  AND value = '"Hello! I''m Nova. I have access to your workspace, can run shell commands, read and write files, and remember our previous conversations. What would you like to work on?"';
```

**Step 2: Refactor `_get_platform_persona()` to `_get_platform_identity()` in runner.py**

Replace `_get_platform_persona()` (lines 264-284) with:

```python
async def _get_platform_identity() -> tuple[str, str]:
    """
    Load the AI name and persona from platform_config.
    Returns (name, persona). Defaults to ("Nova", "") on any failure.
    """
    from app.db import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM platform_config WHERE key IN ('nova.name', 'nova.persona')"
            )
        result = {r["key"]: r["value"] for r in rows}
        name = json.loads(result.get("nova.name", '"Nova"')) or "Nova"
        persona = json.loads(result.get("nova.persona", '""')) or ""
        return str(name).strip(), str(persona).strip()
    except Exception as exc:
        log.debug("Could not load platform identity: %s", exc)
        return "Nova", ""
```

**Step 3: Update `_build_nova_context()` to use identity block**

Replace the `_build_nova_context` function (lines 287-345) — the key changes:
- Call `_get_platform_identity()` instead of `_get_platform_persona()`
- Build `## Identity` block at the start with name + persona
- Keep `## Nova Platform Context` for operational info (tools, agents, session)
- Move `## Response Style` to its own section (not nested in platform context)
- Remove the old `persona_block` appendage

```python
async def _build_nova_context(model: str, agent_id: str, session_id: str) -> str:
    """
    Build the context blocks injected into every system prompt.

    Order (static -> dynamic for prompt cache hit rate):
      1. ## Identity        — name + persona from platform_config
      2. ## Platform Context — tools, active agents, session info
      3. ## Response Style   — formatting rules
    """
    from app.store import list_agents

    # Load identity and agent list concurrently
    identity_task = _get_platform_identity()
    agents_task = _safe_list_agents(agent_id)

    (name, persona), agents_block = await asyncio.gather(identity_task, agents_task)

    # 1. Identity block
    identity_lines = [
        "## Identity",
        f"Your name is {name}. You are a helpful AI assistant with persistent memory.",
        "You remember previous conversations and can use tools to help users.",
    ]
    if persona:
        identity_lines.append("")
        identity_lines.append(persona)
    identity_block = "\n".join(identity_lines)

    # 2. Platform context
    platform_block = (
        f"## Platform Context\n"
        f"- Your model:    {model}\n"
        f"- Your agent ID: {agent_id}\n"
        f"- Session ID:    {session_id}\n"
        f"\n### Active agents in this instance:\n"
        f"{agents_block}\n"
        f"\n### Tools available to you:\n"
        f"  Platform:   list_agents, get_agent_info, create_agent, list_available_models, send_message_to_agent\n"
        f"  Filesystem: list_dir, read_file, write_file\n"
        f"  Shell:      run_shell (runs in workspace, hard timeout {settings.shell_timeout_seconds}s)\n"
        f"  Search:     search_codebase (ripgrep across workspace files)\n"
        f"  Git:        git_status, git_diff, git_log, git_commit\n"
        f"\nWorkspace root: {settings.workspace_root}  (all file/shell paths are relative to this)\n"
        f"Answer model-identity questions using 'Your model' above (never guess)."
    )

    # 3. Response style
    style_block = (
        "## Response Style\n"
        "This is a professional developer tool. Follow these rules in every response:\n"
        "- No emoji except as explicit status indicators\n"
        "- No markdown bold/italic for single characters or trivial emphasis\n"
        "- Do not bold the word 'I' or wrap single letters in ** markers\n"
        "- Use plain prose for explanations; tables for structured data; code blocks for code\n"
        "- Be concise and precise — prefer one clear sentence over three vague ones\n"
        "- Never add filler phrases like 'Great question!', 'Certainly!', or 'Of course!'"
    )

    return f"{identity_block}\n\n{platform_block}\n\n{style_block}"
```

Extract the agent-listing logic into a helper so `_build_nova_context` stays clean:

```python
async def _safe_list_agents(agent_id: str) -> str:
    """Format the active agents list, returning a safe fallback on error."""
    from app.store import list_agents
    try:
        all_agents = await list_agents()
        active = [a for a in all_agents if a.status.value != "stopped"]
        if active:
            lines = []
            for a in sorted(active, key=lambda x: x.created_at):
                marker = " <- YOU" if str(a.id) == agent_id else ""
                lines.append(
                    f"  - {a.config.name}  id={a.id}"
                    f"  model={a.config.model}  status={a.status.value}{marker}"
                )
            return "\n".join(lines)
        return "  (none registered yet)"
    except Exception as e:
        log.warning("Could not fetch agent list for nova_context: %s", e)
        return "  (unavailable)"
```

**Step 4: Simplify `default_system_prompt` in config.py**

In `orchestrator/app/config.py`, change lines 12-15:

```python
    default_system_prompt: str = (
        "You are a helpful AI assistant with persistent memory. "
        "You remember previous conversations and can use tools to help users."
    )
```

This is now a DB-unreachable fallback only — the identity block handles naming.

**Step 5: Add `/api/v1/identity` endpoint in router.py**

Add a new public endpoint (no admin auth required) that returns the resolved name and greeting:

```python
@router.get("/api/v1/identity")
async def get_identity() -> dict:
    """Public endpoint returning the AI's display name and greeting.
    No auth required — used by the dashboard UI."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value FROM platform_config "
            "WHERE key IN ('nova.name', 'nova.greeting')"
        )
    config = {r["key"]: json.loads(r["value"]) for r in rows}
    name = config.get("nova.name") or "Nova"
    greeting_template = config.get("nova.greeting") or ""
    greeting = greeting_template.replace("{name}", name) if greeting_template else ""
    return {"name": name, "greeting": greeting}
```

Add `import json` at the top of router.py if not already present.

**Step 6: Remove hardcoded system prompt from chat-api session.py**

In `chat-api/app/session.py`, change the agent creation (lines 47-58) to use a generic prompt:

```python
    async with httpx.AsyncClient(base_url=settings.orchestrator_url, timeout=30.0) as client:
        resp = await client.post("/api/v1/agents", json={
            "config": {
                "name": settings.default_agent_name,
                "system_prompt": (
                    "You are a helpful AI assistant with persistent memory across conversations. "
                    "You are thoughtful, accurate, and concise. You remember what users tell you and "
                    "reference past context when relevant."
                ),
                "model": settings.default_model,
            }
        })
```

The identity block in `_build_nova_context()` will inject the actual name and persona.

**Step 7: Commit backend changes**

```bash
git add orchestrator/app/agents/runner.py orchestrator/app/config.py \
  orchestrator/app/router.py orchestrator/app/migrations/013_identity_greeting.sql \
  chat-api/app/session.py
git commit -m "feat: unified identity system — dynamic name/persona in system prompt

- Replace _get_platform_persona() with _get_platform_identity()
- Build ## Identity block from nova.name + nova.persona
- Add public /api/v1/identity endpoint for dashboard
- Simplify default_system_prompt to DB-fallback only
- Remove hardcoded 'You are Nova' from chat-api
- Migration 013: update greeting to use {name} placeholder"
```

---

### Task 2: Frontend — Identity hook + NavBar + Chat

**Files:**
- Create: `dashboard/src/hooks/useNovaIdentity.ts`
- Modify: `dashboard/src/components/NavBar.tsx`
- Modify: `dashboard/src/pages/Chat.tsx:228,266,269,295`
- Modify: `dashboard/src/api.ts` (add identity fetch)

**Step 1: Add identity API function in api.ts**

At the end of `dashboard/src/api.ts`, add:

```typescript
// ── Identity ─────────────────────────────────────────────────────────────────

export interface NovaIdentity {
  name: string
  greeting: string
}

export const getNovaIdentity = () =>
  apiFetch<NovaIdentity>('/api/v1/identity')
```

**Step 2: Create the `useNovaIdentity` hook**

Create `dashboard/src/hooks/useNovaIdentity.ts`:

```typescript
import { useQuery } from '@tanstack/react-query'
import { getNovaIdentity } from '../api'

export function useNovaIdentity() {
  const { data } = useQuery({
    queryKey: ['nova-identity'],
    queryFn: getNovaIdentity,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  return {
    name: data?.name ?? 'Nova',
    greeting: data?.greeting ?? '',
  }
}
```

**Step 3: Update NavBar to use dynamic name**

In `dashboard/src/components/NavBar.tsx`:

Add import at top:
```typescript
import { useNovaIdentity } from '../hooks/useNovaIdentity'
```

Inside the `NavBar` component function, add:
```typescript
const { name } = useNovaIdentity()
```

Replace the hardcoded span (line 31):
```tsx
<span className="text-sm font-semibold tracking-widest text-accent-700 dark:text-accent-400 uppercase">{name}</span>
```

**Step 4: Update Chat page to use dynamic name + greeting**

In `dashboard/src/pages/Chat.tsx`:

Add import:
```typescript
import { useNovaIdentity } from '../hooks/useNovaIdentity'
```

Inside the `Chat` component, add:
```typescript
const { name: aiName, greeting } = useNovaIdentity()
```

Replace hardcoded "Nova" references:
- Line 228: `<h1 ...>Nova</h1>` → `<h1 ...>{aiName}</h1>`
- Line 240: `title="Override Nova's default model..."` → `title={`Override ${aiName}'s default model...`}`
- Line 266: `"Start a conversation with Nova"` → `` {`Start a conversation with ${aiName}`} ``
- Line 268-269: `"Nova has persistent memory..."` → `` {`${aiName} has persistent memory, can use tools, and remembers previous sessions.`} ``
- Line 295: `placeholder="Message Nova…"` → `` placeholder={`Message ${aiName}...`} ``

Also update the mobile chat hero in Overview — but that file is being deleted (Task 3), so skip it.

**Step 5: Commit frontend identity changes**

```bash
git add dashboard/src/api.ts dashboard/src/hooks/useNovaIdentity.ts \
  dashboard/src/components/NavBar.tsx dashboard/src/pages/Chat.tsx
git commit -m "feat: dynamic AI name in navbar and chat UI

- Add useNovaIdentity hook backed by /api/v1/identity
- NavBar shows configurable name instead of hardcoded 'Nova'
- Chat page header, placeholder, and empty state use dynamic name"
```

---

### Task 3: Remove Overview page + update routing

**Files:**
- Delete: `dashboard/src/pages/Overview.tsx`
- Modify: `dashboard/src/App.tsx:8,68`
- Modify: `dashboard/src/components/NavBar.tsx:7` (remove Overview from nav links)

**Step 1: Update App.tsx — remove Overview import and route**

In `dashboard/src/App.tsx`:

Remove line 8:
```typescript
import { Overview } from './pages/Overview'
```

Change line 68:
```typescript
            <Route path="/"        element={<Overview />} />
```
to:
```typescript
            <Route path="/"        element={<Chat />} />
```

**Step 2: Update NavBar — remove Overview link**

In `dashboard/src/components/NavBar.tsx`, remove the Overview entry from `mainLinks` (line 7):
```typescript
  { to: '/',         label: 'Overview', icon: Activity         },
```

And update the Chat link to point to `/`:
```typescript
  { to: '/',         label: 'Chat',     icon: MessageSquare    },
```

Remove the old Chat link (line 8):
```typescript
  { to: '/chat',     label: 'Chat',     icon: MessageSquare    },
```

Also remove `Activity` from the lucide-react import since it's no longer used.

**Step 3: Delete Overview.tsx**

```bash
rm dashboard/src/pages/Overview.tsx
```

**Step 4: Commit**

```bash
git add dashboard/src/App.tsx dashboard/src/components/NavBar.tsx
git rm dashboard/src/pages/Overview.tsx
git commit -m "feat: remove Overview page, make Chat the default landing page

- Delete Overview.tsx
- Route / now renders Chat
- Remove Overview from NavBar links"
```

---

### Task 4: Move System Services panel to Settings

**Files:**
- Modify: `dashboard/src/pages/Settings.tsx`

**Step 1: Add System Status section to Settings**

In `dashboard/src/pages/Settings.tsx`:

Add imports for the queue stats and MCP APIs at the top (alongside existing imports from `../api`):
```typescript
import { getQueueStats, getMCPServers } from '../api'
```

Add `Cpu, Layers, Plug, RefreshCw` to the lucide-react import (check which are already imported — `Loader2` and `Activity` are already there).

Add a `SystemStatus` component (place it before the `Settings` export function):

```typescript
function SystemStatus() {
  const { data: queueStats, isError: queueError } = useQuery({
    queryKey: ['queue-stats'],
    queryFn: getQueueStats,
    refetchInterval: 10_000,
    staleTime: 5_000,
    retry: 1,
  })

  const { data: mcpServers = [] } = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: getMCPServers,
    refetchInterval: 15_000,
    staleTime: 10_000,
  })
  const enabledServers = mcpServers.filter((s: { enabled: boolean }) => s.enabled)
  const connectedServers = mcpServers.filter((s: { connected: boolean }) => s.connected)
  const totalTools = connectedServers.reduce((sum: number, s: { tool_count?: number }) => sum + (s.tool_count ?? 0), 0)

  const orchestratorOk = !queueError && queueStats !== undefined
  const rows = [
    { label: 'Queue Worker', ok: orchestratorOk, detail: queueStats ? `depth ${queueStats.queue_depth}` : undefined },
    { label: 'Reaper', ok: orchestratorOk, detail: 'stale-agent recovery' },
    {
      label: 'MCP Servers',
      ok: enabledServers.length > 0 && connectedServers.length === enabledServers.length,
      detail: enabledServers.length === 0
        ? 'none configured'
        : `${connectedServers.length}/${enabledServers.length} connected · ${totalTools} tools`,
    },
  ]

  return (
    <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
      {rows.map(r => (
        <div key={r.label} className="flex items-center justify-between py-2 first:pt-0 last:pb-0">
          <span className="text-sm text-neutral-700 dark:text-neutral-300">{r.label}</span>
          <div className="flex items-center gap-2">
            {r.detail && <span className="text-xs text-neutral-500 dark:text-neutral-400">{r.detail}</span>}
            <span className={`h-2 w-2 rounded-full ${r.ok ? 'bg-emerald-500' : 'bg-neutral-300 dark:bg-neutral-600'}`} />
          </div>
        </div>
      ))}
    </div>
  )
}
```

Then add the section inside the Settings return, after the Recovery & Services section (or wherever feels right — after Nova Identity makes sense since it's system-level):

```tsx
      <Section
        icon={Activity}
        title="System Status"
        description="Live status of internal services. Auto-refreshes every 10 seconds."
      >
        <SystemStatus />
      </Section>
```

**Step 2: Commit**

```bash
git add dashboard/src/pages/Settings.tsx
git commit -m "feat: add System Status section to Settings (moved from Overview)"
```

---

### Task 5: Verify and test

**Step 1: TypeScript build check**

```bash
cd dashboard && npm run build
```

Expected: Clean build, no errors.

**Step 2: Run integration tests**

```bash
cd /home/jeremy/workspace/nova && make test-quick
```

Expected: Health checks pass.

**Step 3: Manual verification checklist**

- [ ] NavBar shows configured name (change `nova.name` in Settings, see it update)
- [ ] Chat header, placeholder, empty state show dynamic name
- [ ] Chat greeting uses `{name}` substitution
- [ ] `/` route renders Chat page
- [ ] Overview route returns 404 / redirects to Chat
- [ ] System Status appears in Settings
- [ ] AI responses use correct name from `## Identity` block
- [ ] Changing persona in Settings affects AI behavior in next message

**Step 4: Final commit (if any fixups needed)**

```bash
git add -u
git commit -m "fix: address any issues from identity system testing"
```
