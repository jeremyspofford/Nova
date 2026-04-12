# 15–16 Data Models and API Contracts

This document defines the shared schemas and core HTTP contracts for Nova Suite. It is intended to stabilize the system boundary between Nova-lite, Nova Board, workflow adapters, state adapters, voice, observability, and future implementation work.

## Purpose

The architecture pack now defines vision, capability boundaries, platform structure, deployment modes, and subsystem ownership. This document adds the common nouns and verbs that the rest of the system will use.

In practice, that means:
- data models define the shared objects
- API contracts define the stable interaction surface
- future subsystem specs should reuse these models instead of inventing new ones

The design target is implementation-neutral but specific enough for Claude to translate into actual application code.

---

# 15 – Shared Data Models

## Design principles

- IDs should be globally unique and string-based.
- Timestamps should use ISO 8601 UTC.
- Enums should be represented as strings in APIs.
- Records should be append-friendly and audit-friendly.
- Risk, approval, and provenance should be first-class concerns.
- Models should support both local-first and cloud-optional deployment modes.

## Event

Represents something that happened in or around Nova.

### Fields
- `id`: string
- `type`: string
- `source`: string
- `subject`: string
- `payload`: object
- `timestamp`: string
- `correlation_id`: string | null
- `priority`: `low` | `normal` | `high` | `critical`
- `risk_class`: `low` | `medium` | `high`
- `actor_type`: `user` | `agent` | `system` | `external`
- `actor_id`: string | null
- `entity_refs`: string[]
- `task_ref`: string | null

### Notes
Typical examples include Home Assistant state changes, webhook arrivals, workflow completions, scheduled heartbeat events, voice commands, and approval responses.

## Task

Represents a unit of work that Nova tracks, reasons about, and possibly executes.

### Fields
- `id`: string
- `title`: string
- `description`: string | null
- `status`: `inbox` | `ready` | `running` | `waiting` | `needs_approval` | `done` | `failed` | `cancelled`
- `goal`: string | null
- `origin_event_id`: string | null
- `board_column_id`: string | null
- `owner_type`: `user` | `agent` | `system`
- `owner_id`: string | null
- `created_at`: string
- `updated_at`: string
- `due_at`: string | null
- `priority`: `low` | `normal` | `high` | `urgent`
- `risk_class`: `low` | `medium` | `high`
- `approval_required`: boolean
- `last_decision`: `none` | `planned` | `acted` | `deferred` | `asked` | `ignored` | `escalated`
- `next_check_at`: string | null
- `result_summary`: string | null
- `labels`: string[]
- `metadata`: object

### Notes
A task is the shared unit across Nova-lite, the board, workflows, approvals, and observability.

## Tool

Represents an action-capable capability that Nova can invoke through an internal module or adapter.

### Fields
- `name`: string
- `display_name`: string
- `description`: string
- `adapter_type`: `internal` | `n8n` | `windmill` | `home_assistant` | `http` | `shell` | `provider`
- `input_schema`: object
- `output_schema`: object | null
- `risk_class`: `low` | `medium` | `high`
- `requires_approval`: boolean
- `timeout_seconds`: number
- `enabled`: boolean
- `tags`: string[]

## Run

Represents an execution instance for a tool call, task action, or workflow.

### Fields
- `id`: string
- `task_id`: string | null
- `tool_name`: string | null
- `workflow_ref`: string | null
- `status`: `queued` | `running` | `succeeded` | `failed` | `cancelled`
- `started_at`: string | null
- `finished_at`: string | null
- `input`: object | null
- `output`: object | null
- `error`: string | null
- `created_at`: string
- `executor_type`: `agent` | `workflow` | `user` | `system`
- `executor_id`: string | null

## Approval

Represents a human decision gate for risky actions.

### Fields
- `id`: string
- `task_id`: string
- `requested_by`: string
- `requested_at`: string
- `summary`: string
- `consequence`: string | null
- `options`: string[]
- `status`: `pending` | `approved` | `denied` | `cancelled`
- `decided_by`: string | null
- `decided_at`: string | null
- `decision`: string | null
- `reason`: string | null

## BoardColumn

Represents a task board column.

### Fields
- `id`: string
- `name`: string
- `order`: number
- `status_filter`: object | null
- `work_in_progress_limit`: number | null
- `description`: string | null

### Recommended initial columns
- Inbox
- Ready
- Running
- Waiting
- Needs Approval
- Done
- Failed

## Entity

Represents an external thing Nova observes or controls.

### Fields
- `id`: string
- `external_id`: string
- `source`: string
- `type`: string
- `name`: string
- `state`: object
- `last_seen_at`: string | null
- `metadata`: object | null
- `capabilities`: string[]
- `room_or_group`: string | null

### Notes
Examples include Home Assistant devices, sensors, switches, lights, services, pipelines, endpoints, jobs, or business systems.

## LLMProviderProfile

Represents an available language model provider endpoint.

### Fields
- `id`: string
- `name`: string
- `provider_type`: `local` | `cloud`
- `endpoint_ref`: string
- `model_ref`: string
- `enabled`: boolean
- `supports_tools`: boolean
- `supports_streaming`: boolean
- `privacy_class`: `local_only` | `cloud_allowed`
- `cost_class`: `low` | `medium` | `high`
- `latency_class`: `low` | `medium` | `high`
- `notes`: string | null

### Notes
This model exists so Nova can remain local-first while still supporting optional cloud LLM use through a common provider abstraction.

---

# 16 – Core API Contracts

These APIs are logical contracts, not framework-specific implementations. Authentication, pagination envelopes, error codes, and transport refinements can be specified later, but the resource shapes and system semantics should remain stable.

## Events API

### POST `/events`
Create or ingest an event.

Request body:
- `type`
- `source`
- `subject`
- `payload`
- `priority` (optional)
- `risk_class` (optional)
- `correlation_id` (optional)
- `actor_type` (optional)
- `actor_id` (optional)
- `entity_refs` (optional)
- `task_ref` (optional)

Response:
- `id`
- `timestamp`

### GET `/events`
List events with filters.

Suggested filters:
- `type`
- `source`
- `priority`
- `risk_class`
- `correlation_id`
- `task_ref`
- `limit`
- `offset`

## Tasks API

### GET `/tasks`
List tasks.

Filters:
- `status`
- `owner_type`
- `owner_id`
- `board_column_id`
- `priority`
- `risk_class`
- `approval_required`
- `limit`
- `offset`

Response:
- `tasks`: Task[]

### POST `/tasks`
Create a task.

Request body:
- `title`
- `description` (optional)
- `goal` (optional)
- `origin_event_id` (optional)
- `owner_type` (optional)
- `owner_id` (optional)
- `priority` (optional)
- `risk_class` (optional)
- `approval_required` (optional)
- `due_at` (optional)
- `labels` (optional)
- `metadata` (optional)

### GET `/tasks/{id}`
Fetch a task and optionally expand related runs and approvals.

### PATCH `/tasks/{id}`
Update mutable task fields.

Allowed updates may include:
- `title`
- `description`
- `status`
- `board_column_id`
- `owner_type`
- `owner_id`
- `priority`
- `due_at`
- `next_check_at`
- `result_summary`
- `labels`
- `metadata`

## Board API

### GET `/board`
Return board columns and task groupings.

Response:
- `columns`: BoardColumn[]
- `tasks_by_column`: record keyed by column ID

### PATCH `/board/tasks/{id}`
Move a task to a different board column.

Request body:
- `board_column_id`

## Tools API

### GET `/tools`
List tools.

### GET `/tools/{name}`
Get one tool definition.

### POST `/tools/{name}/invoke`
Invoke a tool.

Request body:
- `task_id` (optional)
- `input`
- `requested_by` (optional)

Response:
- `run_id`
- `status`

## Runs API

### GET `/runs/{id}`
Fetch a run.

### GET `/tasks/{id}/runs`
List runs related to a task.

### GET `/runs`
List runs with filters such as:
- `task_id`
- `tool_name`
- `status`
- `executor_type`
- `limit`
- `offset`

## Approvals API

### POST `/tasks/{id}/approvals`
Request approval for a task.

Request body:
- `summary`
- `consequence` (optional)
- `options` (optional)

### GET `/approvals/{id}`
Fetch one approval request.

### POST `/approvals/{id}/respond`
Submit a decision.

Request body:
- `decision`
- `reason` (optional)
- `decided_by`

## Entities API

### GET `/entities`
List observed or controllable entities.

Filters may include:
- `source`
- `type`
- `room_or_group`
- `capability`

### GET `/entities/{id}`
Fetch one entity.

### POST `/entities/sync`
Trigger a sync from an external state provider such as Home Assistant.

## LLM Providers API

### GET `/llm/providers`
List configured model providers.

### GET `/llm/providers/{id}`
Fetch one provider profile.

### POST `/llm/route`
Route an inference request through the configured provider abstraction.

Request body:
- `purpose`
- `input`
- `privacy_preference` (`local_preferred` | `local_required` | `cloud_allowed`)
- `tool_use_required` (boolean, optional)
- `latency_preference` (optional)
- `cost_preference` (optional)

Response:
- `provider_id`
- `model_ref`
- `run_id` (optional)
- `output`

## Health and System API

### GET `/health`
Return aggregate health.

### GET `/system/info`
Return deployment mode, enabled subsystems, and provider summary.

---

# Design notes for later subsystem specs

- Nova-lite should primarily operate on `Event`, `Task`, `Run`, `Approval`, and `LLMProviderProfile`.
- Nova Board should primarily operate on `Task`, `BoardColumn`, `Run`, and `Approval`.
- Workflow adapters should translate external workflow execution into `Tool` and `Run` records.
- Home Assistant and future state adapters should map external systems into `Entity` records and emit `Event` objects.
- Voice should usually emit `Event` objects and consume task or run outcomes.

This document should be treated as the shared schema baseline for the next phase of subsystem specs.
