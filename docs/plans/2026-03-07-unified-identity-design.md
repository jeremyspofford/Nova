# Unified AI Identity System

**Date:** 2026-03-07
**Status:** Approved

## Problem

Nova's identity is fragmented across multiple hardcoded locations and disconnected config systems:

- Per-agent `system_prompt` in Redis says "You are Nova" (editable from Overview page)
- `nova.name` in `platform_config` (Postgres) is stored but never read by backend
- `nova.persona` in `platform_config` works but is appended as a footnote
- `nova.greeting` in `platform_config` is stored but never served
- "Nova" is hardcoded in NavBar, Chat page header/placeholder, chat-api session creation

Setting a custom name and persona in Settings has no effect on actual AI behavior or UI display.

## Solution

Single source of truth: `platform_config` in Postgres. Three keys drive everything:

- **`nova.name`** — AI name, used in system prompt + all UI surfaces
- **`nova.persona`** — Rich identity/personality, injected as first-class `## Identity` block
- **`nova.greeting`** — Initial chat message, supports `{name}` placeholder for auto-update

### System Prompt Assembly (new order)

```
1. ## Identity                    <- NEW: from nova.name + nova.persona
   "Your name is {name}. ..."
2. ## Nova Platform Context       <- existing: tools, agents, session info
3. ## Response Style              <- existing: formatting rules
4. ## Relevant memories           <- existing: dynamic memory context
```

### Backend Changes

1. **`orchestrator/app/agents/runner.py`**
   - `_get_platform_persona()` -> `_get_platform_identity()` — loads both `nova.name` and `nova.persona`
   - `_build_nova_context()` — builds `## Identity` block first, keeps platform context separate
   - Response Style rules moved out of the platform context string

2. **`orchestrator/app/config.py`**
   - `default_system_prompt` becomes minimal fallback (DB-unreachable case only)

3. **`orchestrator/app/router.py`**
   - New endpoint `GET /api/v1/identity` — returns `{ name, greeting }` (no auth required, for UI)

4. **`chat-api/app/session.py`**
   - Remove hardcoded "You are Nova" system prompt
   - Use generic base prompt; orchestrator's identity block handles naming

5. **Migration** — update default greeting to use `{name}` placeholder

### Frontend Changes

1. **New hook: `useNovaIdentity()`** — fetches name + greeting from `/api/v1/identity`
2. **NavBar** — dynamic name from hook instead of hardcoded "Nova"
3. **Chat page** — header, placeholder, empty-state, greeting all use dynamic name
4. **Overview page** — removed entirely; Chat becomes `/` route
5. **System Services panel** — moved from Overview to Settings page
6. **Settings → Nova Identity** — unchanged (Name, Greeting, Persona fields)

### Greeting Auto-Update

The greeting stored in `platform_config` uses `{name}` as a placeholder. When served via the identity endpoint, `{name}` is resolved to the current `nova.name` value. Default:

```
Hello! I'm {name}. I have access to your workspace, can run shell commands, read and write files, and remember our previous conversations. What would you like to work on?
```

## Files Changed

### Backend
- `orchestrator/app/agents/runner.py` — identity loading + prompt assembly
- `orchestrator/app/config.py` — simplify default_system_prompt
- `orchestrator/app/router.py` — add identity endpoint, remove system_prompt from agent PATCH
- `orchestrator/app/migrations/013_identity_greeting.sql` — update greeting default
- `chat-api/app/session.py` — remove hardcoded prompt

### Frontend
- `dashboard/src/hooks/useNovaIdentity.ts` — new hook
- `dashboard/src/components/NavBar.tsx` — dynamic name
- `dashboard/src/pages/Chat.tsx` — dynamic name + greeting
- `dashboard/src/pages/Overview.tsx` — deleted
- `dashboard/src/pages/Settings.tsx` — add System Status section
- `dashboard/src/App.tsx` (or router config) — remove Overview route, Chat becomes `/`
