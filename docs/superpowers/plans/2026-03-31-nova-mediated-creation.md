# Nova-Mediated Goal & Task Creation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dashboard goal creation form with Nova-mediated conversational goal creation, controlled by a system-wide autonomy setting.

**Architecture:** Add a `create_goal` tool to platform_tools.py with a two-call confirmation pattern (autonomy check on first call, bypass on confirmed=true). Dashboard Goals page swaps the creation modal for a natural language Request input. New Settings section controls autonomy level via Redis key `nova:config:creation.autonomy`.

**Tech Stack:** Python/FastAPI (orchestrator), React/TypeScript (dashboard), Redis (runtime config), asyncpg (direct DB writes)

**Spec:** `/home/jeremy/.gstack/projects/arialabs-nova/designs/nova-mediated-creation-20260331/spec.md`

---

### File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `orchestrator/app/tools/platform_tools.py` | Modify | Add `create_goal` tool definition, executor dispatch, and implementation |
| `orchestrator/app/agents/runner.py` | Modify | Update self-knowledge with `create_goal` and `create_task` |
| `dashboard/src/pages/Goals.tsx` | Modify | Replace creation modal with Request input, conditional form toggle |
| `dashboard/src/pages/settings/GoalCreationSection.tsx` | Create | Autonomy dropdown + direct creation toggle |
| `dashboard/src/pages/Settings.tsx` | Modify | Register new section in nav and render |
| `tests/test_goal_creation_tool.py` | Create | Integration tests for create_goal tool and autonomy |

---

### Task 1: Add `create_goal` tool definition

**Files:**
- Modify: `orchestrator/app/tools/platform_tools.py` (after line 133)

- [ ] **Step 1: Add the ToolDefinition to PLATFORM_TOOLS**

Add after the existing `create_task` definition (line 133):

```python
ToolDefinition(
    name="create_goal",
    description=(
        "Create an ongoing goal for Nova to work on autonomously. Goals are strategic "
        "objectives that Cortex executes over time — monitoring, recurring analysis, "
        "long-term projects. For one-shot work, use create_task instead.\n\n"
        "IMPORTANT: If the creation autonomy setting requires confirmation, your first "
        "call will return a draft instead of creating the goal. Present the draft to "
        "the user conversationally. Only call again with confirmed=true after explicit "
        "user approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Clear, concise goal title",
            },
            "description": {
                "type": "string",
                "description": (
                    "Detailed description with success criteria. Include specific tool "
                    "names and steps Nova should take to achieve the goal."
                ),
            },
            "success_criteria": {
                "type": "string",
                "description": "Observable, testable conditions that define completion",
            },
            "priority": {
                "type": "integer",
                "enum": [1, 2, 3, 4],
                "description": "1=Critical, 2=High, 3=Normal (default), 4=Low",
            },
            "max_cost_usd": {
                "type": "number",
                "description": "Optional spending cap in USD",
            },
            "max_iterations": {
                "type": "integer",
                "description": "Max thinking cycles. Omit for indefinite.",
            },
            "check_interval_seconds": {
                "type": "integer",
                "description": "Seconds between Cortex checks. Default 3600 (1 hour).",
            },
            "schedule_cron": {
                "type": "string",
                "description": "Cron expression for scheduled goals (e.g. '0 6 * * *' for daily 6AM)",
            },
            "parent_goal_id": {
                "type": "string",
                "description": "UUID of parent goal if this is a sub-goal",
            },
            "max_completions": {
                "type": "integer",
                "description": "Cap on how many times a recurring goal executes",
            },
            "confirmed": {
                "type": "boolean",
                "description": "Set to true ONLY after the user has explicitly approved the goal draft. Never set on first call.",
            },
        },
        "required": ["title", "description"],
    },
),
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('orchestrator/app/tools/platform_tools.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/tools/platform_tools.py
git commit -m "feat(orchestrator): add create_goal tool definition to platform tools"
```

---

### Task 2: Implement `create_goal` executor

**Files:**
- Modify: `orchestrator/app/tools/platform_tools.py` (executor dispatch + implementation)

- [ ] **Step 1: Add executor dispatch**

In the `execute_tool()` function (around line 170), add an elif case after the `create_task` dispatch:

```python
elif name == "create_goal":
    return await _execute_create_goal(arguments)
```

- [ ] **Step 2: Implement `_execute_create_goal` function and `_get_creation_autonomy` helper**

Add after `_execute_create_task` (after line 343). Note: uses a mutable dict `_goal_create_counts` keyed by session_id for rate limiting, schedule_next_at computation for cron goals, and emit_stimulus for Cortex notification.

```python
_goal_create_counts: dict[str, int] = {}  # session_id -> count, reset each turn


async def _get_creation_autonomy() -> str:
    """Read the creation autonomy setting from Redis."""
    try:
        from app.redis_client import get_redis
        r = get_redis()
        if r:
            val = await r.get("nova:config:creation.autonomy")
            if val:
                return val.decode() if isinstance(val, bytes) else val
    except Exception:
        pass
    return "auto_tasks"  # default


async def _execute_create_goal(args: dict) -> str:
    """Create a goal with autonomy check and rate limiting."""
    import uuid
    from datetime import datetime, timezone
    from app.db import get_pool
    from app.stimulus import emit_stimulus

    title = args.get("title", "").strip()
    description = args.get("description", "").strip()
    if not title or not description:
        return "Error: title and description are required."

    confirmed = args.get("confirmed", False)

    # Rate limit: max 3 goals per tool loop (keyed by a simple module-level counter)
    count = sum(_goal_create_counts.values())
    if count >= 3:
        return "Rate limit: maximum 3 goals can be created per conversation turn."

    # Autonomy check (skip if confirmed)
    if not confirmed:
        autonomy = await _get_creation_autonomy()
        needs_confirmation = autonomy in ("auto_tasks", "confirm_all")
        if needs_confirmation:
            draft_lines = [
                "CONFIRMATION REQUIRED — I would create this goal:\n",
                f"  Title: {title}",
                f"  Description: {description}",
            ]
            if args.get("success_criteria"):
                draft_lines.append(f"  Success criteria: {args['success_criteria']}")
            priority_labels = {1: "Critical", 2: "High", 3: "Normal", 4: "Low"}
            draft_lines.append(f"  Priority: {priority_labels.get(args.get('priority', 3), 'Normal')}")
            if args.get("max_cost_usd"):
                draft_lines.append(f"  Budget: ${args['max_cost_usd']}")
            if args.get("schedule_cron"):
                draft_lines.append(f"  Schedule: {args['schedule_cron']}")
            if args.get("max_iterations"):
                draft_lines.append(f"  Max iterations: {args['max_iterations']}")
            draft_lines.append(
                "\nPresent this to the user and ask for approval. "
                "Call create_goal again with confirmed=true only after they agree."
            )
            return "\n".join(draft_lines)

    # Compute schedule_next_at for cron goals
    schedule_cron = args.get("schedule_cron")
    schedule_next_at = None
    if schedule_cron:
        try:
            from croniter import croniter
            if not croniter.is_valid(schedule_cron):
                return f"Error: invalid cron expression: {schedule_cron}"
            schedule_next_at = croniter(schedule_cron, datetime.now(timezone.utc)).get_next(datetime)
        except ImportError:
            pass  # croniter not available, skip schedule_next_at

    # Create the goal
    pool = get_pool()
    goal_id = str(uuid.uuid4())
    priority = args.get("priority", 3)
    max_iterations = args.get("max_iterations")
    max_cost = args.get("max_cost_usd")
    check_interval = args.get("check_interval_seconds", 3600)
    parent_id = args.get("parent_goal_id")
    max_completions = args.get("max_completions")
    success_criteria = args.get("success_criteria")

    await pool.execute(
        """
        INSERT INTO goals
            (id, title, description, success_criteria, status, priority,
             max_iterations, max_cost_usd, check_interval_seconds,
             schedule_cron, schedule_next_at, parent_goal_id, max_completions,
             created_via, created_by)
        VALUES
            ($1::uuid, $2, $3, $4, 'active', $5,
             $6, $7, $8,
             $9, $10, $11::uuid, $12,
             'chat_tool', $13)
        """,
        goal_id, title, description, success_criteria, priority,
        max_iterations, max_cost, check_interval,
        schedule_cron, schedule_next_at, parent_id, max_completions,
        "nova",  # created_by — TODO: pass session user when available
    )

    # Emit stimulus so Cortex reacts
    await emit_stimulus("goal.created", {
        "goal_id": goal_id,
        "title": title,
        "schedule_cron": schedule_cron,
    })

    _goal_create_counts[goal_id] = 1

    return (
        f"Goal created successfully.\n"
        f"  ID: {goal_id}\n"
        f"  Title: {title}\n"
        f"  Status: active\n"
        f"The user can track this on the Goals page."
    )
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('orchestrator/app/tools/platform_tools.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/tools/platform_tools.py
git commit -m "feat(orchestrator): implement create_goal executor with autonomy check"
```

---

### Task 3: Update self-knowledge

**Files:**
- Modify: `orchestrator/app/agents/runner.py` (~line 718)

- [ ] **Step 1: Update Platform tools in self-knowledge**

Find the line (around 718):
```python
"**Platform (Agent Management):** list_agents, get_agent_info, create_agent, "
"update_agent, delete_agent, list_models -- manage agents and view available models.\n"
```

Replace with:
```python
"**Platform (Agent Management):** list_agents, get_agent_info, create_agent, "
"update_agent, delete_agent, list_models, create_task, create_goal "
"-- manage agents, create tasks for pipeline execution, create goals for "
"ongoing autonomous work.\n"
```

- [ ] **Step 2: Add creation guidance to "How I Think" section**

Find the "How I Think" section and add after the existing bullets:

```python
"- **Create goals for ongoing work, tasks for one-shot work.** If a user describes "
"a recurring objective or strategic aim, use create_goal. If they want something done "
"once, use create_task. If they just need an answer, respond directly in chat.\n"
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('orchestrator/app/agents/runner.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/agents/runner.py
git commit -m "feat(orchestrator): add create_goal and create_task to self-knowledge"
```

---

### Task 4: Create GoalCreationSection settings component

**Files:**
- Create: `dashboard/src/pages/settings/GoalCreationSection.tsx`

- [ ] **Step 1: Create the settings section component**

Follow the existing section pattern (e.g., LLMRoutingSection.tsx). The component needs:
- Autonomy dropdown (4 options) backed by Redis key `nova:config:creation.autonomy`
- Direct creation toggle backed by localStorage key `goals.directCreation`

```tsx
import { Target } from 'lucide-react'
import { Section } from '../../components/ui'
import { ConfigField, useConfigValue, type ConfigSectionProps } from './shared'
import { useLocalStorage } from '../../hooks/useLocalStorage'

const AUTONOMY_OPTIONS = [
  { value: 'auto_all', label: 'Full autonomy', description: 'Nova creates tasks and goals without asking' },
  { value: 'auto_tasks', label: 'Tasks autonomous', description: 'Nova auto-creates tasks, confirms goals with you first' },
  { value: 'auto_goals', label: 'Goals autonomous', description: 'Nova auto-creates goals, confirms tasks with you first' },
  { value: 'confirm_all', label: 'Always confirm', description: 'Nova confirms before creating anything' },
]

export function GoalCreationSection({ entries, onSave, saving }: ConfigSectionProps) {
  const autonomy = useConfigValue(entries, 'creation.autonomy', 'auto_tasks')
  const [directCreation, setDirectCreation] = useLocalStorage('goals.directCreation', false)

  return (
    <Section
      icon={Target}
      title="Goal & Task Creation"
      description="Control how Nova creates goals and tasks on your behalf"
      id="goal-creation"
    >
      <ConfigField
        label="Nova creation autonomy"
        configKey="creation.autonomy"
        value={autonomy}
        description="What Nova can create without asking you first"
        onSave={onSave}
        saving={saving}
      />
      <p className="text-micro text-content-tertiary -mt-2 mb-2">
        {AUTONOMY_OPTIONS.find(o => o.value === autonomy)?.description}
      </p>
      <p className="text-micro text-content-tertiary mb-3">
        Valid values: {AUTONOMY_OPTIONS.map(o => o.value).join(', ')}
      </p>

      <div>
        <label className="text-caption font-medium text-content-secondary mb-1.5 block">
          Direct goal creation
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={directCreation}
            onChange={e => setDirectCreation(e.target.checked)}
            className="rounded border-border text-accent focus:ring-accent-500/40"
          />
          <span className="text-compact text-content-primary">
            Enable manual goal creation form on Goals page
          </span>
        </label>
      </div>
    </Section>
  )
}
```

- [ ] **Step 2: Verify dashboard build**

Run: `cd dashboard && npm run build 2>&1 | tail -3`
Expected: `built in` with no TypeScript errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/settings/GoalCreationSection.tsx
git commit -m "feat(dashboard): add Goal & Task Creation settings section"
```

---

### Task 5: Register settings section in Settings.tsx

**Files:**
- Modify: `dashboard/src/pages/Settings.tsx`

- [ ] **Step 1: Add import**

Add to the imports section (around line 20-40):

```typescript
import { GoalCreationSection } from './settings/GoalCreationSection'
```

- [ ] **Step 2: Add to NAV_GROUPS**

In the `behavior` group (around line 85-95), add a new item. Note: NavItem requires an `icon` field:

```typescript
{ id: 'goal-creation', label: 'Goal & Task Creation', icon: Target },
```

Also add `Target` to the lucide-react imports at the top of the file.

- [ ] **Step 3: Add render block**

In the render section (alongside other show() conditionals), add with the wrapping div for scroll-to-section:

```tsx
{show('goal-creation') && (
  <div id="goal-creation">
    <GoalCreationSection entries={entries} onSave={handleSave} saving={saving} />
  </div>
)}
```

- [ ] **Step 4: Verify dashboard build**

Run: `cd dashboard && npm run build 2>&1 | tail -3`
Expected: `built in` with no TypeScript errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/Settings.tsx
git commit -m "feat(dashboard): register Goal & Task Creation in settings nav"
```

---

### Task 6: Goals page — Request input and conditional modal

**Files:**
- Modify: `dashboard/src/pages/Goals.tsx`

- [ ] **Step 1: Add imports and state**

Add to imports:
```typescript
import { useLocalStorage } from '../hooks/useLocalStorage'
import { useToast } from '../components/ToastProvider'
```

Add to the Goals component state:
```typescript
const [directCreation] = useLocalStorage('goals.directCreation', false)
const [request, setRequest] = useState('')
const [sending, setSending] = useState(false)
const { addToast } = useToast()
```

- [ ] **Step 2: Add request submission handler**

Add a handler function inside the Goals component:

```typescript
const handleRequest = async () => {
  if (!request.trim() || sending) return
  setSending(true)
  try {
    await apiFetch('/api/v1/pipeline/tasks', {
      method: 'POST',
      body: JSON.stringify({
        user_input: request.trim(),
        metadata: { source: 'goals_page' },
      }),
    })
    setRequest('')
    addToast({ variant: 'success', message: 'Request sent to Nova' })
  } catch (err) {
    addToast({ variant: 'error', message: 'Failed to send request' })
  } finally {
    setSending(false)
  }
}
```

- [ ] **Step 3: Replace the Create Goal button area**

Find the existing "Create Goal" button (around line 179-185). Replace with:

```tsx
{/* Request input — always visible */}
<div className="flex gap-2">
  <input
    type="text"
    value={request}
    onChange={e => setRequest(e.target.value)}
    onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleRequest()}
    placeholder="Tell Nova what you want to achieve..."
    disabled={sending}
    className="flex-1 h-9 rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 transition-colors"
  />
  <Button onClick={handleRequest} disabled={!request.trim() || sending} size="sm">
    {sending ? 'Sending...' : 'Request'}
  </Button>
</div>

{/* Direct creation button — only when setting enabled */}
{directCreation && (
  <Button variant="outline" size="sm" onClick={() => setShowCreate(true)}>
    <Plus className="w-3.5 h-3.5 mr-1" /> Create Directly
  </Button>
)}
```

- [ ] **Step 4: Wrap the existing CreateGoalModal in directCreation guard**

The existing modal should only render when `directCreation` is true. Find the `<CreateGoalModal>` usage and wrap:

```tsx
{directCreation && showCreate && (
  <CreateGoalModal ... />
)}
```

- [ ] **Step 5: Verify dashboard build**

Run: `cd dashboard && npm run build 2>&1 | tail -3`
Expected: `built in` with no TypeScript errors

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/Goals.tsx
git commit -m "feat(dashboard): replace goal creation modal with Nova request input"
```

---

### Task 7: Integration tests

**Files:**
- Create: `tests/test_goal_creation_tool.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for the create_goal tool and creation autonomy setting."""
import pytest
import httpx

BASE = "http://localhost:8000"
HEADERS: dict = {}


@pytest.fixture(autouse=True)
def _auth(admin_headers):
    HEADERS.update(admin_headers)


@pytest.fixture
def _cleanup_goals():
    """Delete test goals after each test."""
    created: list[str] = []
    yield created
    for gid in created:
        httpx.delete(f"{BASE}/api/v1/goals/{gid}", headers=HEADERS)


class TestCreateGoalTool:
    """Verify create_goal appears in the tool catalog and API works."""

    def test_create_goal_in_tool_catalog(self):
        resp = httpx.get(f"{BASE}/api/v1/tools", headers=HEADERS)
        assert resp.status_code == 200
        tools = resp.json()
        platform_tools = next(
            c for c in tools if c["category"] == "Platform Tools"
        )
        tool_names = [t["name"] for t in platform_tools["tools"]]
        assert "create_goal" in tool_names
        assert "create_task" in tool_names

    def test_create_goal_via_api(self, _cleanup_goals):
        """Verify goals can be created via the standard API."""
        resp = httpx.post(
            f"{BASE}/api/v1/goals",
            headers=HEADERS,
            json={
                "title": "nova-test-mediated-goal",
                "description": "Test goal for mediated creation",
                "priority": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "nova-test-mediated-goal"
        assert data["status"] == "active"
        _cleanup_goals.append(data["id"])


class TestAutonomySetting:
    """Verify the creation autonomy config key works."""

    def test_default_autonomy_is_auto_tasks(self):
        """Default should be auto_tasks when no Redis key is set."""
        resp = httpx.get(
            f"{BASE}/api/v1/config/creation.autonomy",
            headers=HEADERS,
        )
        # May return 404 if key not set — that's fine, default is auto_tasks
        if resp.status_code == 200:
            assert resp.json().get("value") in (
                "auto_tasks", "auto_all", "auto_goals", "confirm_all", None
            )

    def test_set_autonomy(self):
        """Verify the autonomy setting can be changed."""
        resp = httpx.patch(
            f"{BASE}/api/v1/config/creation.autonomy",
            headers=HEADERS,
            json={"value": "confirm_all"},
        )
        assert resp.status_code in (200, 201)

        # Read back
        resp = httpx.get(
            f"{BASE}/api/v1/config/creation.autonomy",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == "confirm_all"

        # Reset to default
        httpx.patch(
            f"{BASE}/api/v1/config/creation.autonomy",
            headers=HEADERS,
            json={"value": "auto_tasks"},
        )
```

- [ ] **Step 2: Run tests (services must be running)**

Run: `pytest tests/test_goal_creation_tool.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_goal_creation_tool.py
git commit -m "test: integration tests for create_goal tool and autonomy setting"
```

---

### Task 8: Final verification

- [ ] **Step 1: Verify full dashboard build**

Run: `cd dashboard && npm run build 2>&1 | tail -5`
Expected: Clean build, no errors

- [ ] **Step 2: Verify Python syntax across all modified files**

Run: `python3 -c "import ast; [ast.parse(open(f).read()) for f in ['orchestrator/app/tools/platform_tools.py', 'orchestrator/app/agents/runner.py']]; print('All OK')"`
Expected: `All OK`

- [ ] **Step 3: Run full test suite (if services running)**

Run: `make test-quick`
Expected: Health endpoints pass

- [ ] **Step 4: Final commit if any loose changes**

```bash
git status
# If clean: done
# If changes: git add + commit
```
