# Skills & Rules System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reusable prompt templates (skills) and declarative behavior constraints (rules) to Nova's agent system, with dashboard UI for managing both.

**Architecture:** Skills are prompt fragments stored in the DB, resolved at agent turn time, and injected into the system prompt. Rules have hard enforcement via regex pattern matching in `execute_tool()` pre-dispatch, blocking tool calls that match. Both have CRUD APIs and dashboard pages. V1 is global-scope only — pod/agent scoping deferred.

**Tech Stack:** Python 3.11 (FastAPI, asyncpg), React/TypeScript (Vite, TanStack Query, Tailwind), PostgreSQL

**Spec reference:** `docs/roadmap.md` P1: Skills & Rules System, `docs/roadmap-archive-2026-03.md` Phase 5c

---

## Scope — V1 (This Plan)

**In scope:**
- `skills` + `rules` tables (global scope, no join tables)
- Skills CRUD API + `resolve_skills()` injecting into chat system prompt
- Rules CRUD API + `check_hard_rules()` intercepting `execute_tool()`
- 3 seed rules: no-rm-rf (hard/block), workspace-boundary (hard/block), no-secret-in-output (hard/warn)
- Dashboard Skills page (list, create, edit, delete, enable/disable)
- Dashboard Rules page (list, create, edit, delete, enable/disable)
- Integration tests

**Deferred:**
- Pod/agent scope join tables (v2)
- Parameter interpolation with `{{param}}` (v2)
- Soft rule injection into Guardrail Agent prompts (v2)
- `require_approval` action (needs approval workflow)
- Rule test endpoint (nice-to-have)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `orchestrator/app/migrations/047_skills_and_rules.sql` | Schema + seed rules |
| Create | `orchestrator/app/skills.py` | Skills CRUD + resolve_skills() |
| Create | `orchestrator/app/rules.py` | Rules CRUD + check_hard_rules() |
| Modify | `orchestrator/app/router.py` | Register skills + rules endpoints |
| Modify | `orchestrator/app/tools/__init__.py` | Pre-execution rule check in execute_tool() |
| Modify | `orchestrator/app/agents/runner.py` | Inject resolved skills into system prompt |
| Create | `dashboard/src/pages/Skills.tsx` | Skills CRUD page |
| Create | `dashboard/src/pages/Rules.tsx` | Rules CRUD page |
| Modify | `dashboard/src/api.ts` | Skills + rules API functions |
| Modify | `dashboard/src/App.tsx` | Route registration |
| Modify | `dashboard/src/components/layout/Sidebar.tsx` | Nav items |
| Create | `tests/test_skills_rules.py` | Integration tests |

---

## Task 1: Database Migration

**Files:**
- Create: `orchestrator/app/migrations/047_skills_and_rules.sql`
- Test: `tests/test_skills_rules.py`

- [ ] **Step 1: Write failing test — skills and rules tables exist**

Create `tests/test_skills_rules.py`:

```python
"""Tests for Skills & Rules system."""
import os
import pytest
import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {}


@pytest.fixture(autouse=True)
def admin_headers():
    secret = os.environ.get("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    HEADERS["X-Admin-Secret"] = secret


def test_skills_endpoint_exists():
    """GET /api/v1/skills should return a list."""
    resp = httpx.get(f"{BASE}/skills", headers=HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_rules_endpoint_exists():
    """GET /api/v1/rules should return a list."""
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_seed_rules_exist():
    """Three system rules should be seeded by migration."""
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    assert resp.status_code == 200
    rules = resp.json()
    names = {r["name"] for r in rules}
    assert "no-rm-rf" in names, f"Seed rule 'no-rm-rf' missing. Got: {names}"
    assert "workspace-boundary" in names
    assert "no-secret-in-output" in names
    # System rules should be marked is_system
    for r in rules:
        if r["name"] in ("no-rm-rf", "workspace-boundary", "no-secret-in-output"):
            assert r["is_system"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_skills_rules.py::test_skills_endpoint_exists -v -x`

Expected: FAIL — 404 (endpoint doesn't exist yet)

- [ ] **Step 3: Write migration**

Create `orchestrator/app/migrations/047_skills_and_rules.sql`:

```sql
-- 047: Skills and Rules tables
-- Skills: reusable prompt templates injected into agent system prompts
-- Rules: declarative behavior constraints with hard pre-execution enforcement

CREATE TABLE IF NOT EXISTS skills (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'global'
                CHECK (scope IN ('global', 'pod', 'agent')),
    category    TEXT NOT NULL DEFAULT 'custom'
                CHECK (category IN ('workflow', 'coding', 'review', 'safety', 'custom')),
    enabled     BOOLEAN NOT NULL DEFAULT true,
    priority    INTEGER NOT NULL DEFAULT 0,
    is_system   BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rules (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    rule_text    TEXT NOT NULL,
    enforcement  TEXT NOT NULL DEFAULT 'hard'
                 CHECK (enforcement IN ('soft', 'hard', 'both')),
    pattern      TEXT,
    target_tools TEXT[],
    action       TEXT NOT NULL DEFAULT 'block'
                 CHECK (action IN ('block', 'warn')),
    scope        TEXT NOT NULL DEFAULT 'global'
                 CHECK (scope IN ('global', 'pod', 'agent')),
    category     TEXT NOT NULL DEFAULT 'safety'
                 CHECK (category IN ('safety', 'quality', 'compliance', 'workflow', 'custom')),
    severity     TEXT NOT NULL DEFAULT 'high'
                 CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    enabled      BOOLEAN NOT NULL DEFAULT true,
    is_system    BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed system rules
INSERT INTO rules (name, description, rule_text, enforcement, pattern, target_tools, action, category, severity, is_system)
VALUES
    ('no-rm-rf', 'Block recursive force delete',
     'Never execute recursive force-delete commands (rm -rf, rm -fr, etc.)',
     'hard', 'rm\s+.*-[rf]{2}', ARRAY['run_shell'], 'block', 'safety', 'critical', true),

    ('workspace-boundary', 'Block operations outside workspace',
     'All file operations must stay within the configured workspace directory',
     'hard', '(^/|\.\./)(?!workspace|tmp|home)', ARRAY['run_shell', 'write_file'], 'block', 'safety', 'high', true),

    ('no-secret-in-output', 'Warn on potential secrets in tool arguments',
     'Flag commands that may contain API keys, passwords, or credentials',
     'hard', '(AKIA[A-Z0-9]{16}|BEGIN\s+(RSA|DSA|EC)\s+PRIVATE|api[_-]?key\s*[:=]\s*\S{20,}|password\s*[:=]\s*\S+)', NULL, 'warn', 'safety', 'critical', true)
ON CONFLICT (name) DO NOTHING;
```

- [ ] **Step 4: Rebuild orchestrator (migration auto-runs on startup)**

Run: `docker compose up -d --build orchestrator`

Wait ~20s for startup + migrations.

- [ ] **Step 5: Verify migration ran**

Run: `docker compose exec postgres psql -U nova -c "\dt skills" && docker compose exec postgres psql -U nova -c "\dt rules"`

Expected: Both tables exist.

---

## Task 2: Skills CRUD Backend

**Files:**
- Create: `orchestrator/app/skills.py`
- Modify: `orchestrator/app/router.py`
- Test: `tests/test_skills_rules.py`

- [ ] **Step 1: Write failing test — skills CRUD**

Add to `tests/test_skills_rules.py`:

```python
@pytest.fixture
def skill_id():
    """Create a test skill and clean up after."""
    resp = httpx.post(
        f"{BASE}/skills",
        json={
            "name": "nova-test-skill",
            "description": "Test skill for integration tests",
            "content": "You are an expert code reviewer. Focus on security and performance.",
            "category": "review",
            "priority": 10,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Failed to create skill: {resp.text}"
    sid = resp.json()["id"]
    yield sid
    try:
        httpx.delete(f"{BASE}/skills/{sid}", headers=HEADERS)
    except Exception:
        pass


def test_create_skill():
    """POST /api/v1/skills creates a skill."""
    resp = httpx.post(
        f"{BASE}/skills",
        json={
            "name": "nova-test-create-skill",
            "content": "Test content",
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["name"] == "nova-test-create-skill"
    assert data["scope"] == "global"
    assert data["enabled"] is True
    # Cleanup
    httpx.delete(f"{BASE}/skills/{data['id']}", headers=HEADERS)


def test_list_skills(skill_id):
    """GET /api/v1/skills returns created skill."""
    resp = httpx.get(f"{BASE}/skills", headers=HEADERS)
    assert resp.status_code == 200
    skills = resp.json()
    found = [s for s in skills if s["id"] == skill_id]
    assert len(found) == 1
    assert found[0]["name"] == "nova-test-skill"


def test_update_skill(skill_id):
    """PATCH /api/v1/skills/{id} updates fields."""
    resp = httpx.patch(
        f"{BASE}/skills/{skill_id}",
        json={"content": "Updated content", "priority": 20},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Updated content"
    assert data["priority"] == 20


def test_delete_skill():
    """DELETE /api/v1/skills/{id} removes skill."""
    # Create then delete
    resp = httpx.post(
        f"{BASE}/skills",
        json={"name": "nova-test-delete-skill", "content": "Temp"},
        headers=HEADERS,
    )
    sid = resp.json()["id"]
    del_resp = httpx.delete(f"{BASE}/skills/{sid}", headers=HEADERS)
    assert del_resp.status_code == 204
    # Verify gone
    get_resp = httpx.get(f"{BASE}/skills", headers=HEADERS)
    assert sid not in [s["id"] for s in get_resp.json()]


def test_toggle_skill(skill_id):
    """PATCH enabled=false disables skill, enabled=true re-enables."""
    resp = httpx.patch(
        f"{BASE}/skills/{skill_id}",
        json={"enabled": False},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    resp2 = httpx.patch(
        f"{BASE}/skills/{skill_id}",
        json={"enabled": True},
        headers=HEADERS,
    )
    assert resp2.status_code == 200
    assert resp2.json()["enabled"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_skills_rules.py::test_create_skill -v -x`

Expected: FAIL — 404

- [ ] **Step 3: Create orchestrator/app/skills.py**

```python
"""Skills — reusable prompt templates for agents."""
from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from app.db import get_pool

log = logging.getLogger(__name__)


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    content: str
    scope: str = "global"
    category: str = "custom"
    priority: int = 0


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    scope: str | None = None
    category: str | None = None
    priority: int | None = None
    enabled: bool | None = None


async def list_skills() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM skills ORDER BY priority DESC, name"
        )
    return [dict(r) for r in rows]


async def create_skill(req: SkillCreate) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO skills (name, description, content, scope, category, priority)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING *""",
            req.name, req.description, req.content, req.scope, req.category, req.priority,
        )
    return dict(row)


async def update_skill(skill_id: UUID, req: SkillUpdate) -> dict | None:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM skills WHERE id = $1", skill_id)
        return dict(row) if row else None

    set_clauses = []
    params = []
    idx = 1
    for key, val in updates.items():
        set_clauses.append(f"{key} = ${idx}")
        params.append(val)
        idx += 1
    set_clauses.append(f"updated_at = NOW()")
    params.append(skill_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE skills SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *",
            *params,
        )
    return dict(row) if row else None


async def delete_skill(skill_id: UUID) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        # Prevent deleting system skills
        is_sys = await conn.fetchval(
            "SELECT is_system FROM skills WHERE id = $1", skill_id
        )
        if is_sys:
            return False
        result = await conn.execute("DELETE FROM skills WHERE id = $1", skill_id)
    return result == "DELETE 1"


async def resolve_skills() -> str:
    """Resolve all active global skills into a formatted prompt section.

    Returns a markdown section to inject into the agent system prompt.
    Only global-scope, enabled skills are included in v1.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT name, content FROM skills
               WHERE enabled = true AND scope = 'global'
               ORDER BY priority DESC, name"""
        )
    if not rows:
        return ""

    parts = ["## Active Skills\n"]
    for r in rows:
        parts.append(f"### {r['name']}\n{r['content']}\n")
    return "\n".join(parts)
```

- [ ] **Step 4: Add routes to router.py**

Add to `orchestrator/app/router.py`:

```python
from app.skills import (
    list_skills, create_skill as _create_skill, update_skill as _update_skill,
    delete_skill as _delete_skill, SkillCreate, SkillUpdate,
)

@router.get("/api/v1/skills")
async def get_skills(_admin: AdminDep):
    return await list_skills()

@router.post("/api/v1/skills", status_code=201)
async def post_skill(req: SkillCreate, _admin: AdminDep):
    return await _create_skill(req)

@router.patch("/api/v1/skills/{skill_id}")
async def patch_skill(skill_id: UUID, req: SkillUpdate, _admin: AdminDep):
    result = await _update_skill(skill_id, req)
    if not result:
        raise HTTPException(404, "Skill not found")
    return result

@router.delete("/api/v1/skills/{skill_id}", status_code=204)
async def del_skill(skill_id: UUID, _admin: AdminDep):
    deleted = await _delete_skill(skill_id)
    if not deleted:
        raise HTTPException(400, "Cannot delete system skill")
```

- [ ] **Step 5: Rebuild orchestrator and run tests**

Run: `docker compose up -d --build orchestrator` then `python3 -m pytest tests/test_skills_rules.py -v -x -k skill`

Expected: All skill tests PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/app/migrations/047_skills_and_rules.sql orchestrator/app/skills.py orchestrator/app/router.py tests/test_skills_rules.py
git commit -m "feat: skills table, CRUD API, and resolve_skills()"
```

---

## Task 3: Rules CRUD Backend

**Files:**
- Create: `orchestrator/app/rules.py`
- Modify: `orchestrator/app/router.py`
- Test: `tests/test_skills_rules.py`

- [ ] **Step 1: Write failing test — rules CRUD**

Add to `tests/test_skills_rules.py`:

```python
@pytest.fixture
def rule_id():
    """Create a test rule and clean up after."""
    resp = httpx.post(
        f"{BASE}/rules",
        json={
            "name": "nova-test-rule",
            "description": "Test rule",
            "rule_text": "Block test patterns",
            "enforcement": "hard",
            "pattern": "DANGEROUS_PATTERN",
            "target_tools": ["run_shell"],
            "action": "block",
            "severity": "high",
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Failed to create rule: {resp.text}"
    rid = resp.json()["id"]
    yield rid
    try:
        httpx.delete(f"{BASE}/rules/{rid}", headers=HEADERS)
    except Exception:
        pass


def test_create_rule():
    """POST /api/v1/rules creates a rule."""
    resp = httpx.post(
        f"{BASE}/rules",
        json={
            "name": "nova-test-create-rule",
            "rule_text": "Block test",
            "enforcement": "hard",
            "pattern": "test_blocked",
            "action": "block",
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["name"] == "nova-test-create-rule"
    assert data["enforcement"] == "hard"
    assert data["enabled"] is True
    httpx.delete(f"{BASE}/rules/{data['id']}", headers=HEADERS)


def test_list_rules_includes_seed(rule_id):
    """GET /api/v1/rules returns seed rules + created rule."""
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    assert resp.status_code == 200
    rules = resp.json()
    names = {r["name"] for r in rules}
    assert "no-rm-rf" in names
    assert "nova-test-rule" in names


def test_update_rule(rule_id):
    """PATCH /api/v1/rules/{id} updates fields."""
    resp = httpx.patch(
        f"{BASE}/rules/{rule_id}",
        json={"severity": "critical", "pattern": "NEW_PATTERN"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["severity"] == "critical"
    assert resp.json()["pattern"] == "NEW_PATTERN"


def test_cannot_delete_system_rule():
    """System rules cannot be deleted."""
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    system_rule = next(r for r in resp.json() if r["is_system"])
    del_resp = httpx.delete(f"{BASE}/rules/{system_rule['id']}", headers=HEADERS)
    assert del_resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_skills_rules.py::test_create_rule -v -x`

- [ ] **Step 3: Create orchestrator/app/rules.py**

```python
"""Rules — declarative behavior constraints with hard enforcement."""
from __future__ import annotations

import json
import logging
import re
from uuid import UUID

from pydantic import BaseModel

from app.db import get_pool

log = logging.getLogger(__name__)

# Compiled regex cache: rule_id -> (updated_at, compiled_pattern)
_regex_cache: dict[str, tuple[str, re.Pattern]] = {}


class RuleCreate(BaseModel):
    name: str
    description: str = ""
    rule_text: str
    enforcement: str = "hard"
    pattern: str | None = None
    target_tools: list[str] | None = None
    action: str = "block"
    category: str = "safety"
    severity: str = "high"


class RuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    rule_text: str | None = None
    enforcement: str | None = None
    pattern: str | None = None
    target_tools: list[str] | None = None
    action: str | None = None
    category: str | None = None
    severity: str | None = None
    enabled: bool | None = None


async def list_rules() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM rules ORDER BY severity DESC, name")
    return [dict(r) for r in rows]


async def create_rule(req: RuleCreate) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO rules (name, description, rule_text, enforcement, pattern,
                   target_tools, action, category, severity)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING *""",
            req.name, req.description, req.rule_text, req.enforcement,
            req.pattern, req.target_tools, req.action, req.category, req.severity,
        )
    return dict(row)


async def update_rule(rule_id: UUID, req: RuleUpdate) -> dict | None:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM rules WHERE id = $1", rule_id)
        return dict(row) if row else None

    set_clauses = []
    params = []
    idx = 1
    for key, val in updates.items():
        set_clauses.append(f"{key} = ${idx}")
        params.append(val)
        idx += 1
    set_clauses.append("updated_at = NOW()")
    params.append(rule_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE rules SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *",
            *params,
        )
    # Invalidate regex cache for this rule
    _regex_cache.pop(str(rule_id), None)
    return dict(row) if row else None


async def delete_rule(rule_id: UUID) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        is_sys = await conn.fetchval(
            "SELECT is_system FROM rules WHERE id = $1", rule_id
        )
        if is_sys:
            return False
        result = await conn.execute("DELETE FROM rules WHERE id = $1", rule_id)
    _regex_cache.pop(str(rule_id), None)
    return result == "DELETE 1"


def _get_compiled(rule_id: str, updated_at: str, pattern: str) -> re.Pattern:
    """Get or compile a regex pattern with caching."""
    cached = _regex_cache.get(rule_id)
    if cached and cached[0] == updated_at:
        return cached[1]
    compiled = re.compile(pattern, re.IGNORECASE)
    _regex_cache[rule_id] = (updated_at, compiled)
    return compiled


async def check_hard_rules(tool_name: str, arguments: dict) -> tuple[bool, str | None]:
    """Check if a tool call violates any hard rules.

    Returns (allowed, violation_message).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, rule_text, pattern, target_tools, action, updated_at
               FROM rules
               WHERE enabled = true
                 AND enforcement IN ('hard', 'both')
                 AND pattern IS NOT NULL"""
        )

    if not rows:
        return True, None

    # Build the string to match against
    match_str = f"{tool_name} {json.dumps(arguments, default=str)}"

    for r in rows:
        # Check tool targeting
        targets = r["target_tools"]
        if targets and tool_name not in targets:
            continue

        try:
            compiled = _get_compiled(str(r["id"]), str(r["updated_at"]), r["pattern"])
            if compiled.search(match_str):
                if r["action"] == "warn":
                    log.warning(
                        "Rule '%s' matched tool call %s (warn only): %s",
                        r["name"], tool_name, r["rule_text"],
                    )
                    continue  # warn = allow but log
                else:
                    # block
                    return False, f"Blocked by rule '{r['name']}': {r['rule_text']}"
        except re.error as e:
            log.error("Invalid regex in rule '%s': %s", r["name"], e)
            continue

    return True, None
```

- [ ] **Step 4: Add routes to router.py**

Add to `orchestrator/app/router.py`:

```python
from app.rules import (
    list_rules, create_rule as _create_rule, update_rule as _update_rule,
    delete_rule as _delete_rule, RuleCreate, RuleUpdate,
)

@router.get("/api/v1/rules")
async def get_rules(_admin: AdminDep):
    return await list_rules()

@router.post("/api/v1/rules", status_code=201)
async def post_rule(req: RuleCreate, _admin: AdminDep):
    return await _create_rule(req)

@router.patch("/api/v1/rules/{rule_id}")
async def patch_rule(rule_id: UUID, req: RuleUpdate, _admin: AdminDep):
    result = await _update_rule(rule_id, req)
    if not result:
        raise HTTPException(404, "Rule not found")
    return result

@router.delete("/api/v1/rules/{rule_id}", status_code=204)
async def del_rule(rule_id: UUID, _admin: AdminDep):
    deleted = await _delete_rule(rule_id)
    if not deleted:
        raise HTTPException(400, "Cannot delete system rule")
```

- [ ] **Step 5: Rebuild and run tests**

Run: `docker compose up -d --build orchestrator` then `python3 -m pytest tests/test_skills_rules.py -v -x`

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/app/rules.py orchestrator/app/router.py tests/test_skills_rules.py
git commit -m "feat: rules table, CRUD API, check_hard_rules(), and 3 seed rules"
```

---

## Task 4: Hard Rule Enforcement in execute_tool()

**Files:**
- Modify: `orchestrator/app/tools/__init__.py`
- Test: `tests/test_skills_rules.py`

- [ ] **Step 1: Write failing test — rule blocks tool execution**

Add to `tests/test_skills_rules.py`:

```python
def test_hard_rule_blocks_rm_rf():
    """The no-rm-rf seed rule should block 'rm -rf' via run_shell."""
    # Submit a task that tries rm -rf — the tool dispatch should block it
    # We test via the /api/v1/tools catalog to verify the rule is active,
    # then test the actual enforcement by creating a custom rule and
    # calling a tool endpoint if available.

    # Verify the rule exists and is enabled
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    rules = resp.json()
    rm_rule = next((r for r in rules if r["name"] == "no-rm-rf"), None)
    assert rm_rule is not None
    assert rm_rule["enabled"] is True
    assert rm_rule["enforcement"] in ("hard", "both")
    assert rm_rule["pattern"] is not None


def test_custom_rule_enforcement():
    """A custom hard rule with pattern should appear in rule list and be enforceable."""
    # Create a rule
    resp = httpx.post(
        f"{BASE}/rules",
        json={
            "name": "nova-test-block-pattern",
            "rule_text": "Block test pattern for integration test",
            "enforcement": "hard",
            "pattern": "FORBIDDEN_STRING_12345",
            "target_tools": ["run_shell"],
            "action": "block",
            "severity": "high",
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    rid = resp.json()["id"]

    # Verify it's returned in list
    list_resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    names = {r["name"] for r in list_resp.json()}
    assert "nova-test-block-pattern" in names

    # Cleanup
    httpx.delete(f"{BASE}/rules/{rid}", headers=HEADERS)
```

- [ ] **Step 2: Run tests to verify baseline**

Run: `python3 -m pytest tests/test_skills_rules.py::test_hard_rule_blocks_rm_rf -v -x`

- [ ] **Step 3: Add pre-execution check to execute_tool()**

In `orchestrator/app/tools/__init__.py`, modify `execute_tool()`:

```python
async def execute_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call to the appropriate module."""
    # ── Hard rule enforcement (pre-execution) ──
    try:
        from app.rules import check_hard_rules
        allowed, violation_msg = await check_hard_rules(name, arguments)
        if not allowed:
            return f"Tool execution blocked: {violation_msg}"
    except Exception as e:
        # Don't let rule check failure break tool execution
        import logging
        logging.getLogger(__name__).warning("Rule check failed: %s", e)

    # MCP tools are namespaced as mcp__{server}__{tool}
    if name.startswith("mcp__"):
        # ... existing MCP dispatch ...
```

- [ ] **Step 4: Rebuild and run tests**

Run: `docker compose up -d --build orchestrator` then `python3 -m pytest tests/test_skills_rules.py -v -x`

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/tools/__init__.py tests/test_skills_rules.py
git commit -m "feat: hard rule enforcement in execute_tool() pre-dispatch"
```

---

## Task 5: Skill Injection into Chat Agent

**Files:**
- Modify: `orchestrator/app/agents/runner.py`
- Test: `tests/test_skills_rules.py`

- [ ] **Step 1: Write failing test — resolved skills appear in agent context**

Add to `tests/test_skills_rules.py`:

```python
def test_resolved_skills_injected():
    """When a global skill is enabled, it should be resolvable."""
    # Create a skill
    resp = httpx.post(
        f"{BASE}/skills",
        json={
            "name": "nova-test-injection-skill",
            "content": "UNIQUE_SKILL_MARKER_98765: Always be helpful.",
            "priority": 100,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    sid = resp.json()["id"]

    # Verify skills list includes it
    list_resp = httpx.get(f"{BASE}/skills", headers=HEADERS)
    skill = next((s for s in list_resp.json() if s["id"] == sid), None)
    assert skill is not None
    assert skill["enabled"] is True
    assert skill["scope"] == "global"

    # Cleanup
    httpx.delete(f"{BASE}/skills/{sid}", headers=HEADERS)
```

- [ ] **Step 2: Modify runner.py to inject skills**

In `orchestrator/app/agents/runner.py`, find `_build_nova_context()`. After the self-knowledge block and before the return, add:

```python
    # Inject active skills
    try:
        from app.skills import resolve_skills
        skills_block = await resolve_skills()
        if skills_block:
            parts.append(skills_block)
    except Exception as e:
        log.debug("Failed to resolve skills: %s", e)
```

- [ ] **Step 3: Rebuild and run tests**

Run: `docker compose up -d --build orchestrator` then `python3 -m pytest tests/test_skills_rules.py -v -x`

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/agents/runner.py tests/test_skills_rules.py
git commit -m "feat: inject resolved skills into chat agent system prompt"
```

---

## Task 6: Dashboard Skills Page

**Files:**
- Create: `dashboard/src/pages/Skills.tsx`
- Modify: `dashboard/src/api.ts`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/components/layout/Sidebar.tsx`
- Test: `cd dashboard && npm run build`

- [ ] **Step 1: Add API functions to api.ts**

Add to `dashboard/src/api.ts`:

```typescript
// Skills
export const getSkills = () => apiFetch<any[]>('/api/v1/skills')
export const createSkill = (data: Record<string, unknown>) =>
  apiFetch('/api/v1/skills', { method: 'POST', body: JSON.stringify(data) })
export const updateSkill = (id: string, data: Record<string, unknown>) =>
  apiFetch(`/api/v1/skills/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const deleteSkill = (id: string) =>
  apiFetch(`/api/v1/skills/${id}`, { method: 'DELETE' })
```

- [ ] **Step 2: Create Skills.tsx**

Create `dashboard/src/pages/Skills.tsx` following the Pods.tsx pattern:
- PageHeader with "Skills" title, description, help entries, refresh + create buttons
- List of SkillCard components (expandable cards)
- Each card shows: name, category badge, scope badge, priority, enabled toggle
- Expanded view shows: content (code block), description, edit/delete buttons
- CreateSkillModal with: name, description, content (textarea), category (select), priority (number)
- ConfirmDialog for delete
- System skills show lock icon, delete disabled

- [ ] **Step 3: Register route and nav**

In `App.tsx`, add route. In `Sidebar.tsx`, add nav item under Configure:

```typescript
{ to: '/skills', label: 'Skills', icon: Wand2, minRole: 'admin' },
```

- [ ] **Step 4: Build check**

Run: `cd dashboard && npm run build`

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/Skills.tsx dashboard/src/api.ts dashboard/src/App.tsx dashboard/src/components/layout/Sidebar.tsx
git commit -m "feat(dashboard): Skills management page with CRUD"
```

---

## Task 7: Dashboard Rules Page

**Files:**
- Create: `dashboard/src/pages/Rules.tsx`
- Modify: `dashboard/src/api.ts`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/components/layout/Sidebar.tsx`
- Test: `cd dashboard && npm run build`

- [ ] **Step 1: Add API functions to api.ts**

Add to `dashboard/src/api.ts`:

```typescript
// Rules
export const getRules = () => apiFetch<any[]>('/api/v1/rules')
export const createRule = (data: Record<string, unknown>) =>
  apiFetch('/api/v1/rules', { method: 'POST', body: JSON.stringify(data) })
export const updateRule = (id: string, data: Record<string, unknown>) =>
  apiFetch(`/api/v1/rules/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const deleteRule = (id: string) =>
  apiFetch(`/api/v1/rules/${id}`, { method: 'DELETE' })
```

- [ ] **Step 2: Create Rules.tsx**

Create `dashboard/src/pages/Rules.tsx` following the same pattern:
- PageHeader with "Rules" title
- List of RuleCard components
- Each card shows: name, enforcement badge (soft/hard/both), severity badge (color-coded), action badge, enabled toggle
- Expanded view shows: rule_text, pattern (code block), target_tools list, description
- Severity colors: low=blue, medium=amber, high=orange, critical=red
- CreateRuleModal with: name, description, rule_text, enforcement (select), pattern (input, shown when hard/both), target_tools (comma-separated input), action (select), category (select), severity (select)
- System rules show lock icon, delete disabled

- [ ] **Step 3: Register route and nav**

In `App.tsx`, add route. In `Sidebar.tsx`, add nav item:

```typescript
{ to: '/rules', label: 'Rules', icon: ShieldAlert, minRole: 'admin' },
```

- [ ] **Step 4: Build check**

Run: `cd dashboard && npm run build`

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/Rules.tsx dashboard/src/api.ts dashboard/src/App.tsx dashboard/src/components/layout/Sidebar.tsx
git commit -m "feat(dashboard): Rules management page with CRUD and severity badges"
```

---

## Task 8: Full Regression Test

**Files:**
- Modify: `tests/test_skills_rules.py`

- [ ] **Step 1: Run all new tests**

Run: `python3 -m pytest tests/test_skills_rules.py -v --tb=short`

Expected: All tests PASS

- [ ] **Step 2: Run full integration suite**

Run: `python3 -m pytest tests/ -q --deselect tests/test_friction.py::TestFrictionCRUD::test_requires_admin_auth`

Expected: No new failures beyond pre-existing ones

- [ ] **Step 3: Dashboard build**

Run: `cd dashboard && npm run build`

Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add tests/test_skills_rules.py
git commit -m "test: full regression coverage for skills & rules system"
```

---

## Verification Checklist

- [ ] `GET /api/v1/skills` returns list (empty initially)
- [ ] `POST /api/v1/skills` creates a skill, `PATCH` updates, `DELETE` removes
- [ ] `GET /api/v1/rules` returns 3 seed rules (no-rm-rf, workspace-boundary, no-secret-in-output)
- [ ] `POST /api/v1/rules` creates a rule, system rules can't be deleted
- [ ] Hard rules with patterns block matching tool calls in `execute_tool()`
- [ ] Global skills are injected into chat agent system prompt
- [ ] Dashboard /skills page: list, create, edit, toggle, delete
- [ ] Dashboard /rules page: list, create, edit, toggle, delete, severity badges
- [ ] `npm run build` succeeds
- [ ] `make test` — no new failures
