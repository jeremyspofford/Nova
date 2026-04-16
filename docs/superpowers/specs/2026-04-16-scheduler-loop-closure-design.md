# Scheduler Loop Closure — Design Spec

**Date:** 2026-04-16
**Status:** Draft — pending review

---

## Goal

Close the gap exposed by the newly-shipped scheduler: scheduled triggers currently fire events that produce failed tasks because no handlers match their payloads. Close the loop so that:

1. Nova's two default triggers (`system-heartbeat`, `daily-summary`) produce useful self-monitoring output landing in the activity log, with escalation to tasks only when something needs attention.
2. Users can define their own scheduled triggers through chat ("every day at 9am, check r/SideProject and summarize top 5 posts"), with natural-language → cron translation handled by the LLM.
3. Both paths ride the existing triage → plan → execute pipeline where it makes sense, and bypass it where it doesn't (deterministic tool-type triggers don't need LLM reasoning per tick).

This is a joint delivery of what was decomposed in brainstorming as **A (close default loop)** and **B (user-defined goal triggers)**.

---

## User Stories — what this looks like from the outside

### Story 1 — silent heartbeat

10:00 UTC. The `system-heartbeat` cron fires. Nova runs a battery of local checks (disk, memory, stale tasks, failed-run rate). All pass. An activity entry appears: `heartbeat: clean`. No task is created. Jeremy's chat UI activity feed shows the entry.

### Story 2 — heartbeat escalates

10:30 UTC. Heartbeat fires. Disk is at 95%. An activity entry appears: `heartbeat: disk at 95% — action needed`. A task is created: `Disk at 95% (/dev/nvme0n1p2)`. The task sits in the pending queue for nova-lite to plan action (or for Jeremy to intervene).

### Story 3 — daily summary

00:00 UTC. The `daily-summary` cron fires. A tool handler gathers the last 24 hours of events, runs, and task transitions; feeds that digest to an LLM; and writes a human-readable summary to the activity log. If there are unresolved stalls, a task is created pointing at them.

### Story 4 — creating a custom trigger via chat

Jeremy types into chat: *"every day at 9am, check r/SideProject and summarize top 5 posts."*

Nova's LLM recognizes the scheduling intent and calls the `scheduler.create_trigger` function with parsed fields (`cron="0 9 * * *"`, `payload={"goal": "Check r/SideProject and summarize top 5 posts"}`). The backend intercepts the call (it's a sensitive op), stores it as a pending action, and replies:

> I'll create this trigger:
> - **Name:** SideProject daily digest
> - **Schedule:** every day at 9:00 UTC (`0 9 * * *`)
> - **Goal:** Check r/SideProject and summarize top 5 posts
>
> Confirm?

Jeremy replies: *"yes"*. Backend commits, POSTs to `/system/triggers`, replies: *"Created."*.

### Story 5 — listing / editing triggers via chat

Jeremy: *"what triggers do I have?"*
Nova: (calls `scheduler.list_triggers`, auto-executes — read-only, no confirm) → replies with a formatted list.

Jeremy: *"pause the SideProject one."*
Nova: (calls `scheduler.update_trigger` → pending confirm) → replies with the proposed change → Jeremy confirms → committed.

### Story 6 — goal-type trigger fires

09:00 UTC next day. `sideproject-daily-digest` cron fires. Event emits with `payload={"goal": "..."}`. Triage creates a task with goal as description. Planner runs the LLM, but there's no `reddit.search` tool in Nova's catalog yet (Layer C). The task ends `failed` with a summary noted in activity: *"Requested capability 'search reddit' unavailable."* This is expected — goal-type triggers depend on tool catalog breadth which is out of scope here.

### Story 7 — Settings panel

Jeremy opens the Settings tab. The existing model picker + LLM config remain. A new **Scheduled Triggers** section lists each trigger: name, schedule (in human-readable form — "every day at 9am UTC"), payload kind (tool/goal), enabled state. Read-only — "To edit, ask Nova in chat." Link to chat.

---

## Architecture

### Pipeline — before and after

```
BEFORE (today, broken):
  scheduler tick → event {source: scheduler, payload: {check: "..."}}
    → triage (LLM)
    → task created
    → planner (LLM)
    → executor: no matching tool → fails
    → task ends "failed"
    → activity: "failed task"

AFTER (tool-type trigger, clean path):
  scheduler tick → event {source: scheduler, payload: {tool: "nova.system_health", input: {}}}
    → triage sees scheduler+tool path, SKIPS LLM
    → invokes nova.system_health directly (creates a Run — activity entry)
    → handler returns {"status": "ok", "message": "disk 42%, mem 31%, 0 stale"}
    → done. Run is the audit trail.

AFTER (tool-type trigger, escalation path):
  scheduler tick → event {source: scheduler, payload: {tool: "nova.system_health", input: {}}}
    → triage sees scheduler+tool path, SKIPS LLM
    → invokes nova.system_health directly (Run)
    → handler returns {"status": "action_needed", "title": "...", "description": "..."}
    → triage creates task from the escalation fields
    → task enters pending queue; nova-lite picks it up next tick

AFTER (goal-type trigger):
  scheduler tick → event {source: scheduler, payload: {goal: "check r/SideProject..."}}
    → triage sees scheduler+goal path, SKIPS classification LLM
    → creates task (title = f"{trigger.name} — {today_iso}", description = goal text)
    → planner (LLM) plans actions → executor → summarizer (LLM) → activity

AFTER (chat-driven creation):
  user message → LLM (tool catalog incl. scheduler.* tools)
    → LLM issues tool_call(scheduler.create_trigger, args=...)
    → backend: sensitive call → stores pending + replies confirmation
    → user replies "yes"
    → backend commits pending → POST /system/triggers → reply "Created"
```

### Components touched

| Layer | Change |
|---|---|
| **DB schema** | Migration `0005`: drop `interval_seconds`, add `cron_expression`; seed-trigger rows rewritten |
| **API models/schemas** | `cron_expression` field + validator; `ScheduledTriggerCreate` schema (new, for POST) |
| **API router** | Add `POST /system/triggers`; `PATCH` validates cron via `croniter.is_valid` |
| **API tool handlers** | Two new handlers: `nova.system_health`, `nova.daily_summary`; four scheduler-management handlers: `scheduler.create_trigger`, `scheduler.list_triggers`, `scheduler.update_trigger`, `scheduler.delete_trigger` |
| **API tool seed** | Register the six new tools |
| **API conversations router** | Replace intent-classifier path with tool-calling loop; add pending-confirmation state on `Conversation` |
| **API config** | `llm_client` provider model switched to `qwen2.5-coder:7b`; seed flips `supports_tools=True` |
| **Nova-lite scheduler** | `_is_due` rewrite using `croniter`; keep `fire_due_triggers` mostly intact |
| **Nova-lite triage** | Branch on `source=="scheduler"`: skip classification LLM; route tool-type → direct invoke; route goal-type → task with goal as description |
| **Board (frontend)** | New Settings section: read-only trigger list; small help text pointing at chat |

---

## Data Model Changes

### Migration `0005_cron_schedules.py`

```python
# upgrade
op.add_column("scheduled_triggers",
    sa.Column("cron_expression", sa.String(), nullable=True))

# data migration: translate existing interval_seconds → cron
op.execute("""
    UPDATE scheduled_triggers SET cron_expression = '*/30 * * * *' WHERE id = 'system-heartbeat';
    UPDATE scheduled_triggers SET cron_expression = '0 0 * * *' WHERE id = 'daily-summary';
""")

# now enforce NOT NULL
op.alter_column("scheduled_triggers", "cron_expression", nullable=False)

op.drop_column("scheduled_triggers", "interval_seconds")
```

Downgrade inverts: re-add `interval_seconds`, drop `cron_expression`, re-seed intervals.

### `ScheduledTrigger` model

Replaces `interval_seconds` with `cron_expression: str NOT NULL`. All other fields unchanged.

### Pydantic schemas

```python
class ScheduledTriggerCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str
    description: str | None = None
    cron_expression: str
    payload_template: dict[str, Any]
    active_hours_start: str | None = Field(default=None, pattern=HHMM_PATTERN)
    active_hours_end: str | None = Field(default=None, pattern=HHMM_PATTERN)
    enabled: bool = True

    @field_validator("cron_expression")
    def _validate_cron(cls, v):
        from croniter import croniter
        if not croniter.is_valid(v):
            raise ValueError(f"invalid cron expression: {v}")
        return v

    @model_validator(mode="after")
    def _validate_payload_kind(self):
        if "tool" in self.payload_template:
            if "goal" in self.payload_template:
                raise ValueError("payload cannot contain both 'tool' and 'goal'")
            # tool-type — 'input' is optional
        elif "goal" in self.payload_template:
            if not isinstance(self.payload_template["goal"], str) or not self.payload_template["goal"].strip():
                raise ValueError("goal must be a non-empty string")
        else:
            raise ValueError("payload must contain either 'tool' or 'goal'")
        return self
```

`ScheduledTriggerUpdate` gains `cron_expression`, `payload_template` as optional patchable fields with the same validators.

### Payload shape convention

```jsonc
// Tool-type
{"tool": "nova.system_health", "input": {}}

// Goal-type
{"goal": "Check r/SideProject and summarize top 5 posts"}
```

Inspected at runtime by shape (`"tool" in payload` vs `"goal" in payload`) — no denormalized `payload_kind` column needed.

### `_is_due` rewrite

```python
from croniter import croniter

def _is_due(trigger: dict, now: datetime) -> bool:
    if not trigger.get("enabled"):
        return False
    last_fired = _parse_last_fired(trigger.get("last_fired_at"))  # aware UTC or None
    base = last_fired or datetime.fromtimestamp(0, tz=timezone.utc)
    next_fire = croniter(trigger["cron_expression"], base).get_next(datetime)
    return now >= next_fire
```

**Catch-up semantics:** if Nova was offline when a cron occurrence passed, the trigger fires the first time `fire_due_triggers` runs after startup. Missed occurrences collapse to at most one fire — no burst replay. The `last_fired_at` update immediately after firing prevents re-fires in the same minute even if the tick takes multiple seconds.

### Active-hours gate (unchanged)

If `active_hours_start` and `active_hours_end` are set, cron occurrences outside the window are skipped. This is a secondary filter on top of cron — e.g., `cron="0 * * * *"` + `active_hours="09:00"-"17:00"` = "every hour, but only during working hours."

---

## Tool Handler Contract

### Return shape (typed response)

All handlers return:

```python
# Clean
{"status": "ok", "message": str}

# Escalation
{"status": "action_needed", "title": str, "description": str, "details": dict | None}
```

The triage branch for scheduler tool-type events reads `status` and routes:
- `ok` → done. The Run record (created by `invoke_tool`) is the audit entry.
- `action_needed` → create a task using `title`, `description`, and optional `details` in the task payload for planner context.

Handlers that today return raw dicts (like `debug.echo`) remain unchanged — they're not designed to be scheduler-invoked. The contract only applies to handlers wired to scheduled triggers.

### Handler: `nova.system_health`

Runs four deterministic checks in-process:

| Check | Threshold | Escalation message |
|---|---|---|
| Disk usage at `/` (container root) | `> 85%` | "Disk at X% (container `/`)" |
| Memory usage | `> 90%` | "Memory at X%" |
| Stale tasks (status in `pending`/`running` > 24h) | count > 0 | "X stale task(s) — review triage pipeline" |
| Failed-run rate (last 1h) | `> 50%` | "X of Y recent runs failed — investigate" |

Implementation — uses `shutil.disk_usage("/")` (container-scoped, which is what matters for Nova's own log/DB volume — host disk is a separate concern outside Nova's observability), `psutil` for memory (add to requirements if not present), DB queries for tasks/runs. Returns on first threshold breach with the escalation info — or `ok` with a one-line `message` summarizing the fleet ("disk 42%, mem 31%, 0 stale, 0/12 runs failed 1h").

### Handler: `nova.daily_summary`

Input: `{"window_hours": 24}` (default).

Flow:
1. Query last N hours of events (via `get_events`), runs (via `get_runs`), task transitions (via DB query).
2. Build a structured digest dict.
3. LLM-summarize the digest with the local provider (`llm_client.route_internal("summarize_daily", messages)`).
4. Returns `{"status": "ok", "message": <full summary text>}`. The Run record itself is the summary artifact — the existing activity feed surfaces Run summaries, so the digest is visible as activity without needing a task.

**Why not action_needed?** A daily summary is not outstanding work — it's a read-once artifact. The Run's output field holds the full summary; activity renders it. Escalating to a task would imply "something needs doing," which misrepresents the intent. If the summary itself *surfaces* an issue (e.g., "12 stalled tasks"), a follow-up task creation is the summary handler's job to emit as a SEPARATE escalation run, not a transformation of the summary artifact.

---

## Chat-Driven Trigger Management

### Conversations backend — from intent classifier to tool-calling loop

**Current path** (per `2026-04-15-chat-agent-wiring-design.md`): one-shot classification → dispatch at most one tool → response call.

**New path:**

```
1. Build message thread + tool catalog from registered handlers.
2. LLM call #1 (with tools): model returns either text or tool_call(s).
3. If tool_call(s):
   a. For each tool_call:
      - If tool is in SENSITIVE_TOOLS set (scheduler.create_*, update_*, delete_*):
          store pending_tool_call on conversation; stream confirmation prompt as assistant reply; STOP loop.
      - Else: dispatch synchronously, collect result, inject as tool-result message.
   b. LLM call #2 (with updated context): model returns text or further tool_calls.
   c. Loop up to `max_tool_turns` (default 3) before forcing a final text response.
4. Stream final assistant text response.
```

**Confirmation resolution on next user turn:**

```
If conversation.pending_tool_call is set:
    If user_message matches confirmation regex (whole-word):
        dispatch the pending tool_call; clear pending; stream result summary.
    Else if user_message matches denial regex (whole-word):
        clear pending; stream "Cancelled."
    Else:
        clear pending (new intent); proceed normally.
```

**Confirmation regex — whole-word match (not substring):**

```python
CONFIRM_RE = re.compile(r"\b(yes|yep|yeah|confirm|confirmed|do it|go ahead|proceed)\b", re.I)
DENY_RE    = re.compile(r"\b(no|nope|cancel|stop|abort|nvm|never ?mind)\b", re.I)
```

Whole-word is essential — substring would match "yesterday" as "yes". Confirm takes precedence over deny if somehow both match (paranoia: "yes, cancel" reads as confirm-yes, scoring the first hit). Allowlist regex keeps the confirmation mechanism dumb-code, not LLM-mediated — avoids edge cases where the model "helpfully" decides a vague message means confirm.

### New database column

`conversations.pending_tool_call: JSONB NULL` — stores the full tool call (name + args) awaiting confirmation. Cleared on confirm/deny/timeout.

Migration `0006_conversation_pending_tool_call.py`.

### SENSITIVE_TOOLS

```python
SENSITIVE_TOOLS = {
    "scheduler.create_trigger",
    "scheduler.update_trigger",
    "scheduler.delete_trigger",
}
```

Read-only tools (`scheduler.list_triggers`, plus `debug.echo`, `fs.list`, `fs.read`, `http.request`, etc.) auto-execute. The set is intentionally small and explicit.

### The four scheduler-management tools

All registered in the tool registry; seeded into the `tools` table with the new `supports_tools=True` provider so the LLM can call them.

**`scheduler.create_trigger`**

Input schema (fields the LLM must populate):
```json
{
  "id": "kebab-case id, unique",
  "name": "human-readable name",
  "description": "optional short description",
  "cron_expression": "standard 5-field cron, UTC",
  "payload": {"tool": "...", "input": {}} | {"goal": "..."},
  "active_hours_start": "HH:MM or null",
  "active_hours_end": "HH:MM or null"
}
```

Handler: POSTs to `/system/triggers` via the API's own SQLAlchemy session (same-process). Returns `{"id": "...", "summary": "Created trigger '...'"}`.

**`scheduler.list_triggers`**

Input: `{}`. Handler queries all triggers, returns `{"triggers": [{id, name, cron_expression, payload_kind, enabled}, ...]}`. Chat LLM formats the list in a human-readable reply.

**`scheduler.update_trigger`**

Input:
```json
{
  "id": "target trigger id",
  "updates": {"enabled": false, "cron_expression": "0 10 * * *", ...}
}
```

Handler: PATCH `/system/triggers/{id}`. Returns `{"summary": "Updated '...': disabled + rescheduled to 10am daily"}`.

**`scheduler.delete_trigger`**

Input: `{"id": "target trigger id"}`.

Handler: DELETE `/system/triggers/{id}` (new API endpoint — adds to `system.py` router, confirms existence, deletes). Returns `{"summary": "Deleted trigger '...'"}`.

### Confirmation reply template

When a sensitive tool is intercepted, the backend streams a confirmation message composed from the pending args. Template (rendered server-side):

```
I'll {verb} this trigger:
- **Name:** {name}
- **Schedule:** {cron_expression_human}  (`{cron_expression}`)
- **{Kind}:** {payload_description}

Confirm?
```

Where `cron_expression_human` comes from a small helper that converts common cron patterns to English ("every day at 9:00 UTC", "every 30 minutes", "weekdays at 10:00 UTC") — handles the 80% common cases; falls back to the raw expression otherwise.

---

## Settings Panel — Read-Only Trigger List

New section in the existing Settings page (after the LLM provider section). Component: `<ScheduledTriggersPanel />`.

Fetches `GET /system/triggers` on mount + on tab focus. Renders:

```
Scheduled Triggers
─────────────────────────────────────────────
  System Heartbeat
    every 30 minutes  •  enabled  •  last fired 3m ago
    runs: nova.system_health

  Daily Summary
    every day at 00:00 UTC  •  enabled  •  last fired 8h ago
    runs: nova.daily_summary

  SideProject daily digest
    every day at 09:00 UTC  •  enabled  •  last fired never
    goal: Check r/SideProject and summarize top 5 posts
─────────────────────────────────────────────
  To add, edit, or remove triggers, ask Nova in chat.
```

~80 lines of TSX using existing fetch/query patterns. Read-only by design — all mutations go through chat.

---

## Model Swap — `qwen2.5-coder:7b`

### Changes

- `config.ollama_model` default: `"llama3.2:3b"` → `"qwen2.5-coder:7b"`
- Seed for `ollama-local` provider: `supports_tools=True`
- Docker-compose ensures model is pulled on nova-api startup (or document `ollama pull qwen2.5-coder:7b` as a prereq — simpler)
- Chat system prompt: no change needed, but verify the model respects its format

### Fallback

If the user's hardware can't run 7b comfortably, they switch back in Settings. The intent-classifier fallback is NOT implemented per user approval of question 6b — if `supports_tools=False` on the active provider, trigger creation via chat is disabled with a clear error message:

> I can't create triggers with the current model. Switch to a tool-capable model in Settings (qwen2.5-coder:7b recommended).

This is consistent with the "no unblock-now-finish-later" rule — we commit to function-calling as the path and accept the model constraint.

---

## Error Handling

| Failure | Behavior |
|---|---|
| Cron expression invalid at PATCH time | 422 from API; chat LLM re-prompted "that cron was invalid — retry" |
| Tool handler raises (crashes) | Run marked `failed`; activity entry shows the error; no task (noise suppression) |
| `action_needed` task can't be created (DB failure) | Run still saved with the escalation payload; log warning; next scheduler tick re-checks (handler is idempotent by design) |
| `post_event` succeeds but `patch_scheduled_trigger(last_fired_at)` fails | Won't happen in the new flow — scheduler still patches first, same as current code |
| Goal-type trigger references missing tool | Existing behavior: planner fails, task marked `failed`, activity entry explains. Acceptable as noted in deferred work |
| Chat pending confirmation never resolved | Cleared on next user message regardless of content if >30 minutes have elapsed (soft timeout). No background sweeper — state sits until user sends a new message. Acceptable because pending rows are harmless until consumed, and a user returning to a stale conversation will trip the timeout on their next message. If this proves annoying, a periodic sweeper is a small follow-up. |
| Model swap → user lacks qwen2.5-coder:7b | API health endpoint includes a `model_ready: bool` field; Settings panel surfaces a "model unavailable" warning with `ollama pull` instructions |

---

## Testing Strategy

### API tests

- `test_system.py`:
  - `test_create_trigger_valid_cron` — POST valid → 200
  - `test_create_trigger_invalid_cron` — POST invalid cron → 422
  - `test_create_trigger_conflicting_payload` — both `tool` and `goal` → 422
  - `test_create_trigger_goal_empty` — `{"goal": ""}` → 422
  - `test_delete_trigger` — DELETE existing → 200, then GET → empty
  - `test_patch_cron_expression` — patch updates cron + validates
  - `test_seed_still_idempotent` — after migration, re-seed doesn't duplicate or clobber

- `test_tool_handlers.py`:
  - `test_nova_system_health_ok` — all checks green → `{status: ok}`
  - `test_nova_system_health_disk_threshold` — mock `disk_usage` high → `{status: action_needed, title contains "Disk"}`
  - `test_nova_system_health_stale_tasks` — seed stale tasks → escalation
  - `test_nova_daily_summary` — build canned events/runs, verify LLM prompt shape (mock llm_client), verify return has `status=action_needed` + title containing date

- `test_conversations.py`:
  - `test_tool_call_non_sensitive_auto_executes` — list_triggers auto-runs
  - `test_tool_call_sensitive_stores_pending` — create_trigger stores pending; reply contains "Confirm?"
  - `test_confirmation_commits_pending` — user says "yes" → pending dispatched, conversation cleared
  - `test_denial_clears_pending` — user says "no" → pending cleared, no side effects
  - `test_new_intent_clears_pending` — user says unrelated message → pending cleared
  - `test_tool_call_loop_max_turns` — model keeps tool-calling → force text response after N

### Nova-lite tests

- `test_scheduler.py`:
  - `test_is_due_cron_never_fired` — `last_fired_at=None` → fires
  - `test_is_due_cron_occurrence_passed` — cron occurrence happened 5min ago, no fire → fires now
  - `test_is_due_cron_future_occurrence` — cron occurrence is 1h away → not due
  - `test_is_due_catchup_once` — 3 occurrences missed → fires once; next tick has `last_fired_at` updated so no replay

- `test_triage.py`:
  - `test_scheduler_tool_event_bypasses_llm` — event with source=scheduler + tool payload → invoke_tool called, no llm_route call
  - `test_scheduler_tool_event_ok_status_no_task` — handler returns ok → no post_task
  - `test_scheduler_tool_event_action_needed_creates_task` — handler returns action_needed → task created with title/description from handler
  - `test_scheduler_goal_event_creates_task_with_goal_description` — goal payload → task with goal text as description

### Board tests (frontend)

- `ScheduledTriggersPanel.test.tsx`:
  - renders empty state (no triggers)
  - renders multiple triggers with human-readable cron
  - refetches on tab focus

### End-to-end smoke test (manual + automated script)

Covered in the implementation plan's Task 7 equivalent — full stack boot, wait 35 minutes, verify heartbeat fired, verify disk-threshold escalation (via mock high disk), verify trigger creation via chat API.

---

## Roadmap / Deferred Work

**These are needed to fully realize the user's ambition** ("check subreddit → generate ideas → build PoC → push to GitHub → set up Cloudflare"). Tracked explicitly so they don't get lost:

### Layer C — Tool Catalog Breadth (separate project)

The goal-type trigger pipeline works structurally after this spec, but goals that reference capabilities Nova doesn't have still fail. To make goals like "check r/SideProject and summarize" work end-to-end, we need:

- `reddit.search(subreddit, sort, limit)` → list of posts
- `reddit.fetch_post(post_id)` → post body + comments
- `github.create_repo(name, private)` → repo URL
- `github.push(repo_url, files)` → commit SHA
- `cloudflare.create_subdomain(zone, record)` → DNS record
- `code.scaffold(template, variables)` → generated project
- `shell.run_long(cmd, timeout_minutes)` → multi-minute command execution

Each is its own tool handler with its own auth flow (Reddit OAuth, GitHub token, Cloudflare API key). Adds incrementally to the tool registry. Existing `http.request` unblocks simple REST APIs; OAuth-gated APIs need dedicated handlers.

### Layer D — Multi-Step Long-Running Orchestration (separate project)

Goal-type triggers currently execute in one planner/executor pass per task. Goals like "build a PoC and deploy it" need:

- Task decomposition: planner generates child tasks, not just actions
- Multi-tick execution state: tasks that need to wait (CI running, async API poll) without blocking the loop
- Workflow DSL or n8n/Windmill integration (per architecture doc `02-04-platform-deployment-subsystems.md`: *"Use n8n/Windmill for workflows"*)
- Checkpoint/resume: if Nova restarts mid-workflow, resume from last step

This is a major subsystem and should get its own design session. Likely pairs with an approvals-at-scale flow — a 20-step workflow deploying code probably wants approval gates at key points (before `git push`, before DNS change, before cost-incurring actions).

### Smaller deferred items

- **Cron-to-NL translation quality.** The human-readable cron converter handles common cases; polish as users encounter edge cases.
- **Trigger run history.** Today each fire creates a Run; no dedicated "last 10 fires of trigger X" view. Add a `trigger_runs` join table or denormalize trigger_id onto Run.
- **Per-trigger retry policy.** If `nova.system_health` fails once, it just logs; no retry. Could add `max_retries` + backoff.
- **Timezone support.** All schedules are UTC; user's "9am" means 9am UTC. If the user wants local time, we add a `timezone` column and use `pytz` in the cron iterator.

---

## Risks & Tradeoffs

**Risk: `qwen2.5-coder:7b` doesn't run well on the user's hardware.**
Mitigation: Settings panel surfaces model status; fallback is to switch to another tool-capable model. If no tool-capable model works, chat-driven management is disabled with a clear error — better than silent degradation.

**Risk: LLM mis-translates natural language to cron.**
Mitigation: strict confirmation step means the user always sees the translated cron (both the expression and a human rendering) before commit. Worst case: user rejects, retries with clearer phrasing.

**Risk: scheduler tool handlers become a catch-all for "things Nova should auto-check."**
Mitigation: the handler contract is explicit — ok/action_needed only. If a "heartbeat check" needs rich output, it's probably actually a goal trigger, not a tool trigger. Keep tool handlers deterministic + cheap.

**Risk: `pending_tool_call` state leaks across conversations.**
Mitigation: scoped to a single conversation row; cleared on new intent; 30-minute soft timeout; explicit deny works.

**Risk: Cron migration loses data if rows get added between the two sub-migrations.**
Mitigation: migration runs in a single transaction (Alembic default); no concurrent writes during upgrade.

---

## Implementation Order (for the follow-on plan)

Numbered for the `writing-plans` skill to consume next:

1. **DB & schema** — Migration 0005 (cron), model update, Create schema, cron validator, re-seed logic.
2. **API endpoints** — POST /system/triggers, DELETE /system/triggers/{id}, PATCH cron validator; tests.
3. **Nova-lite cron** — `_is_due` rewrite with `croniter`, update FakeClient fixtures, all 16 existing scheduler tests migrate; add cron-specific tests.
4. **Tool handler contract & two default handlers** — `nova.system_health`, `nova.daily_summary` with typed return shape; register in tool seed.
5. **Nova-lite triage scheduler-source branching** — tool-type path (direct invoke + status routing), goal-type path (task from goal).
6. **Model swap** — update config + provider seed; document `ollama pull`; add `model_ready` to health check.
7. **Conversations tool-calling loop** — replace classifier, add pending_tool_call column (migration 0006), implement sensitive-tool interception, confirmation regex, loop-turn limit.
8. **Scheduler management tools** — four handlers (`scheduler.create_trigger`, `.list_triggers`, `.update_trigger`, `.delete_trigger`), register in seed.
9. **Settings panel** — `<ScheduledTriggersPanel />` read-only list, cron-to-NL helper.
10. **Integration smoke test** — end-to-end trigger-fires + chat-creates-trigger scenarios in a rebuilt stack.

Each step self-contained; each ends with a green test suite.
