# 07 – Workflow and Tools Specification (MVP)

This document defines how Nova Suite uses workflows and tools in the MVP, focusing on integration with existing systems (n8n, Windmill) rather than building a new first-party workflow engine.

Nova’s philosophy is:
- treat workflows as **attached engines** behind a stable Tool/Run API
- let Nova-lite decide *what* to do and *when*
- let n8n/Windmill (or future Nova Flow) handle *how* a particular multi-step action runs

---

## 1. Purpose and scope

The workflow layer exists to:
- expose external workflows and jobs as `Tool` definitions Nova-lite can invoke
- translate `Tool` invocations into n8n/Windmill runs
- map external workflow state back into Nova `Run` and `Task` records

Out of scope for MVP:
- building a new workflow designer UI
- arbitrary DAG editing inside Nova Board
- multi-tenant workflow hosting

---

## 2. Core concepts

Nova reuses the shared models from `15-16-data-models-and-apis.md`:

- `Tool` – capability that Nova-lite can invoke
- `Run` – one execution of a tool or workflow
- `Task` – unit of work that may be fulfilled by one or more runs

The workflow layer adds the idea of a **workflow adapter**:

- a service that knows how to:
  - call n8n or Windmill APIs
  - translate between Nova `Tool`/`Run` and external workflow/job references
  - receive callbacks/webhooks and update Nova accordingly

---

## 3. Tool definitions (workflow-backed)

For MVP, we define workflow-backed tools as `Tool` records with:

- `adapter_type`: `n8n` or `windmill`
- `name`: a stable identifier used by Nova-lite
- `description`: clear human-readable description
- `input_schema`: JSON Schema describing expected input payload
- `output_schema`: minimal expected structure of results (if any)
- `risk_class` and `requires_approval`: set based on what the workflow does

### Example tool entries

- `home.turn_on_scene`
  - adapter_type: `n8n`
  - description: "Turn on a named Home Assistant scene"
  - input_schema: `{ "type": "object", "properties": { "scene_id": {"type":"string"} }, "required":["scene_id"] }`

- `devops.summarize_ci_failure`
  - adapter_type: `windmill`
  - description: "Summarize a CI job failure and suggest next steps"
  - input_schema: CI event payload or a reduced set (job URL, log snippet)

Nova-lite does not need to know *how* these workflows are built; it only needs to know what inputs they expect and what they claim to do.

---

## 4. Workflow adapter behavior

The workflow adapter is a Nova-owned service responsible for:

- exposing tools to Nova via the `Tool` list
- invoking the correct external workflow or job when Nova-lite calls `/tools/{name}/invoke`
- creating and updating `Run` records
- handling callbacks or polling external systems for status

### Invocation flow (MVP)

1. Nova-lite calls `POST /tools/{name}/invoke`:
   - with `task_id` (optional) and `input` payload

2. Nova API:
   - validates that the tool exists and is enabled
   - persists a new `Run` record with `status=queued`
   - forwards the request to the workflow adapter, along with the `Run` ID

3. Workflow adapter:
   - looks up the tool’s configuration
   - calls the appropriate n8n or Windmill endpoint with mapped input
   - stores the external workflow/job ID inside the `Run.workflow_ref`
   - sets `status=running` and timestamps when execution begins

4. Completion:
   - external system calls back a webhook, or the adapter polls for completion
   - adapter updates the `Run` with `status`, `output`, `error` as appropriate
   - Nova-lite and Nova Board observe the updated run and adjust task state and summaries.

---

## 5. Mapping to n8n and Windmill

### n8n

- Each n8n-based tool corresponds to one or more n8n workflows.
- The adapter calls n8n’s REST API to start a workflow, passing input as JSON.
- n8n is configured to send a webhook back to the workflow adapter on completion or failure.

Configuration items:
- n8n base URL and auth
- mapping from `Tool.name` -> n8n workflow ID or webhook URL

### Windmill

- Each Windmill-based tool corresponds to a script, flow, or job.
- The adapter calls Windmill’s API (e.g., to run a job with parameters).
- Windmill can send webhooks or be polled for job completion.

Configuration items:
- Windmill base URL and auth
- mapping from `Tool.name` -> Windmill job/flow identifier

For both systems, the adapter should keep details out of Nova-lite and the board.

---

## 6. Run lifecycle

`Run` status transitions for workflow-backed tools:

- `queued` – created by Nova API before the external workflow is started
- `running` – external workflow/job has begun
- `succeeded` – external workflow reported success
- `failed` – external workflow reported failure or timed out
- `cancelled` – Nova or the user cancelled the run

Nova-lite is responsible for:
- treating `succeeded`/`failed` as signals for updating task status
- reading `output` to create `result_summary`
- potentially scheduling retries with backoff

The adapter is responsible for:
- moving runs from `queued` to `running`
- updating runs when external systems finish

---

## 7. Error handling and retries

For MVP:

- If the adapter cannot start a workflow, it should mark the `Run` as `failed` with an error message.
- Nova-lite may decide whether to retry based on task labels, risk, and the error message.
- Retries should use simple backoff and be capped to avoid loops.

Longer term, retry policies could live in tool configuration.

---

## 8. Security and approvals

Tools that invoke workflows capable of making impactful changes (e.g., restarting services, modifying infrastructure) should:

- be marked with `risk_class=high`
- set `requires_approval=true`

Nova-lite and the board then ensure that:

- such tools are only called after an `Approval` is created and approved
- audit records include which workflow/job ran, with which parameters

The workflow adapter must never bypass Nova’s policy/approval decisions.

---

## 9. Observability

Workflows are a critical debugging surface. For MVP, the system should:

- record basic metrics (counts of runs by status, per tool)
- emit events for run creation and completion
- include links from tasks to external workflow/job dashboards when possible

This allows you to click through from a Nova task to, say, the n8n or Windmill UI when troubleshooting.

---

## 10. MVP workflows to support

At minimum, the workflow layer should support:

1. **Home routines**
   - Tools that call n8n to orchestrate multi-step home automations (e.g., "Evening routine" that touches several HA devices).

2. **DevOps diagnostics**
   - Tools that call Windmill (or n8n) to gather logs, summarize CI failures, or run checks and surface results back to Nova.

3. **Approval-gated actions**
   - Tools that perform impactful operations only after going through the approval and policy checks defined elsewhere.

These use cases exercise n8n and Windmill in both home and work contexts without requiring Nova to own a full workflow UI in MVP.
