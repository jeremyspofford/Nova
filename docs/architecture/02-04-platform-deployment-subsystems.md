# 02 – Platform Architecture

Nova is structured as a modular platform with multiple planes that separate concerns between **control**, **execution**, **resources/state**, **events**, and **observability**, while still running as a cohesive suite for the user.[web:149][web:211][web:241] The platform architecture describes these planes, the core services in each, and the main flows between them during common scenarios.

## Architectural planes

### Control plane

The control plane owns configuration, policies, service registry, approvals, task boards, and the primary administrative and operator-facing UI/API.[web:149][web:211]

Core responsibilities:
- Manage system configuration and feature flags.
- Store and enforce high-level policies and safety rules.
- Maintain the task board (Nova Board) and approvals surface.
- Provide admin and operator dashboards for tasks, runs, workflows, and services.
- Track service health and registration metadata.

Primary components in this plane:
- **Nova Control** – admin UI and control APIs.
- **Nova Board** – task/approval surface shared between humans and agents.
- **Nova Policy** – cross-cutting safety and approval engine.

### Execution plane

The execution plane owns the actual work done by the system: agent reasoning loops, workflow execution, scheduling, and tool invocation.[web:149][web:236][web:241]

Core responsibilities:
- Run Nova-lite (and later Nova Core) agent loops.
- Execute workflows, jobs, and actions via internal engines or adapters.
- Schedule and run heartbeat cycles and periodic checks.
- Invoke tools against external systems and local resources.

Primary components:
- **Nova-lite / Nova Core** – agent runtime, heartbeat, planning, and decision engine.
- **Workflow engines** – n8n and Windmill initially, later Nova Flow.
- **Nova Tools / Connect adapters** – call connectors and tools through a uniform contract.
- **Scheduler** – cron-like and heartbeat scheduling services.

### Resource and state plane

The resource/state plane represents the external world that Nova observes and acts upon: home devices, services, infrastructure, and any external systems the suite integrates with.[web:235][web:238][web:240]

Core responsibilities:
- Provide a unified view of entities and their state.
- Relay commands to Home Assistant and other resource controllers.
- Abstract over different execution environments (local services, cloud APIs, infrastructure).

Primary components:
- **Home Assistant** – initial home and device state provider.
- **Nova State** – future abstraction layer for entities and resources.
- **External services** – SaaS APIs, repos, CI/CD, and other systems accessed via connectors.

### Event plane

The event plane normalizes triggers and state changes into durable events that agent loops, workflows, and schedulers can process in a consistent way.[web:82][web:95][web:111]

Core responsibilities:
- Accept events from Home Assistant, workflows, webhooks, voice inputs, CI/CD, and internal components.
- Persist events to a durable log for replay, auditing, and recovery.
- Fan out events to interested consumers (agent runtime, workflows, board, observability).

Primary components:
- **Event API** – REST/ingest endpoints for new events.
- **Event log** – durable storage for events (e.g., Postgres or queue-backed log).
- **Event router** – dispatch events to Nova-lite, workflows, and other subscribers.

### Observability plane

The observability plane captures logs, traces, metrics, and audit trails across all other planes, so that behavior is explainable, debuggable, and trustworthy.[web:92][web:193][web:241]

Core responsibilities:
- Collect structured logs and traces from all Nova services and adapters.
- Maintain an audit trail of tasks, approvals, tool invocations, and decisions.
- Provide metrics for health, performance, and usage.

Primary components:
- **Nova Observe** – centralized observability and audit service.
- Logging/metrics sinks – e.g., OpenTelemetry-compatible exporters or local-first equivalents.

## Core data flows

### Event-to-task loop

1. An event enters the system via the Event API or an internal emitter (e.g., Home Assistant event, CI webhook, voice command).[web:82][web:95]
2. The event is normalized and stored in the event log.
3. Nova-lite consumes the event, classifies intent and risk, and either updates an existing task or creates a new one in Nova Memory/Board.
4. Nova Policy evaluates whether the event can drive actions immediately or requires approval.
5. If action is permitted, Nova-lite plans and calls tools via the execution plane (workflows, adapters, scripts).
6. Outputs are written back as task updates and additional events, which may drive further loops.

### Scheduled heartbeat loop

1. The Scheduler triggers a heartbeat event at configured intervals.[web:74][web:86]
2. Nova-lite inspects tasks that are due, waiting, or otherwise requiring follow-up.
3. Nova Policy and any user-set preferences determine whether actions should be proposed, taken, or deferred.
4. Tool invocations run through the workflow and adapter layer as above.
5. All changes are reflected on Nova Board and in audit logs for inspection.

### Human-in-the-loop approval loop

1. A high-risk planned action is flagged by Nova Policy as requiring approval.
2. Nova Board creates or updates a task card in a `Needs Approval` status with a clear summary and consequence description.
3. The user reviews the card in Nova Control and approves or denies.
4. Approval or denial is recorded in the audit trail and emitted as an event.
5. Nova-lite resumes or cancels the planned work based on the decision.

## Ownership and data boundaries

### Data ownership

- **Tasks and memory** – owned by Nova Memory, surfaced through Nova Board and the agent runtime.
- **Events** – owned by the Event plane; other components reference events by ID.
- **Policies and approvals** – owned by Nova Policy; external tools should not enforce conflicting rules.
- **Configuration and registry** – owned by Nova Control.
- **Workflow graphs and run metadata** – initially stored in n8n/Windmill; gradually mirrored or migrated into Nova Flow.

### Boundaries and contracts

Each subsystem communicates via explicit contracts:
- Event ingestion: `POST /events` and internal event topics.
- Task operations: `GET/POST /tasks` and board APIs.
- Tool invocation: `POST /tools/{name}/invoke`.
- Approvals: `POST /tasks/{id}/approve` or similar.
- Policy checks: internal `policy-engine` interfaces.

These contracts should be specified in more detail in the data-model and API-contract documents so that Claude and future builders have unambiguous interfaces.

## Interaction with external tools

Home Assistant, n8n, Windmill, local model runners, and optional cloud LLM providers are treated as **attached engines** rather than core planes: they live primarily in the resource/state and execution planes, behind Nova-owned adapters and provider abstractions.[web:53][web:56][web:238][web:391]

Nova should avoid leaking tool-specific semantics into the control plane and user-facing model wherever possible so that future Nova services can replace those engines without forcing user retraining or major product changes.[web:117][web:123][web:211]

---

# 03 – Deployment Modes

Nova supports three deployment modes at the architectural level: local-only, hybrid, and distributed. The logical platform architecture remains the same, but service placement and scaling patterns differ between modes.[web:235][web:238][web:240]

## Local-only mode

In local-only mode, all core Nova services run on user-controlled hardware (e.g., a home-lab server), often alongside Home Assistant and local model runners.

Characteristics:
- Maximum privacy: events, tasks, memory, and voice data remain local.[web:145][web:155]
- Lower recurring cost but bounded by local compute (CPU, GPU, RAM).
- Simplified networking; most components communicate over a local network.

Typical placement:
- Control plane: local Nova Control + Board.
- Execution plane: Nova-lite, scheduler, adapters, workflows (n8n/Windmill in local containers).
- Resource/state plane: Home Assistant and any other local services.
- Event plane: local event API and log.
- Observability plane: local observability stack and storage.

## Hybrid mode

In hybrid mode, sensitive data and interactive control remain local, while some execution or storage workloads run in a remote environment (e.g., cloud or hosted Kubernetes cluster), including optional cloud model inference when policy and user preference allow it.[web:235][web:240][web:243][web:391]

Characteristics:
- Better scalability and resilience for heavy workloads.
- Local components remain authoritative for privacy-sensitive and latency-sensitive paths (home, voice).
- Requires secure, authenticated communication between local and remote components.

Typical split:
- Control plane: primarily local, with awareness of remote workers.
- Execution plane: Nova-lite and critical logic local; some workflows and tools run remotely.
- Resource/state: Home Assistant local; remote APIs accessed from the cloud as needed.
- Event plane: either replicated or bridged between local and remote segments.
- Observability: aggregated across local and remote through secure collectors.

## Distributed/Kubernetes mode

In distributed mode, Nova services can be deployed across multiple nodes or Kubernetes workers for high availability, horizontal scaling, and workload isolation.[web:147][web:150][web:156]

Characteristics:
- Control plane may run as a small replicated service; execution plane services are scaled as needed.
- Event bus and scheduler need to be explicitly designed for clustered environments (e.g., leader election or idempotent scheduling).
- Observability becomes more important and should rely on standard tracing and metrics.

Typical placement:
- Control plane: replicated Nova Control and Board deployments.
- Execution plane: multiple instances of Nova-lite workers, workflow runners, and tool adapters.
- Event plane: message broker or log with high availability.
- Observability: cluster-aware logging, metrics, and tracing.

The deployment document should be refined later with concrete Docker Compose and Kubernetes examples, but at this stage the goal is to ensure the architecture is compatible with all three modes.

---

# 04 – Subsystems Overview

This overview lists the major subsystems in Nova, what each owns, and how they relate. It ties the capability map to concrete modules to guide implementation and future replacement.

## Core runtime subsystems

- **Nova-lite / Nova Core**  
  Purpose: agent runtime that consumes events, evaluates tasks, plans, and invokes tools.  
  Owns: planning logic, heartbeat behavior (later), and limited runtime configuration.  
  Depends on: Event plane, task store, policy engine, tool registry.

- **Nova Memory**  
  Purpose: persistent storage for tasks, task history, and scoped memory for agent work.  
  Owns: task records, task-run links, short-term task notes, and some summary data.  
  Depends on: Database, event plane for task-related events.

- **Nova Policy**  
  Purpose: enforce safety, approvals, and constraints.  
  Owns: policies, approval rules, risk classes.  
  Depends on: Task and event data; exposes policy decisions to runtime and control plane.

## Work management subsystems

- **Nova Board**  
  Purpose: present tasks and approvals as a lightweight board shared by humans and agents.  
  Owns: board views, column configuration, task-to-column mapping.  
  Depends on: Task store, policy engine, control plane.

- **Approvals UI** (part of Nova Control)  
  Purpose: allow humans to approve, deny, or comment on pending high-risk actions.  
  Owns: approval workflows and user interaction states.  
  Depends on: Nova Board, Nova Policy, audit logs.

## Execution subsystems

- **Workflow layer**  
  Purpose: orchestrate steps into automations and jobs.  
  Owns: workflow definitions (initially in n8n/Windmill), workflow run metadata.  
  Depends on: Tool adapters, event plane, task store.

- **Tool and connector adapters (Nova Tools / Connect)**  
  Purpose: provide a uniform interface to external tools and services.  
  Owns: tool registry entries, adapter configurations.  
  Depends on: External services (Home Assistant, SaaS APIs, scripts).

- **Scheduler**  
  Purpose: trigger heartbeats, periodic checks, and time-based events.  
  Owns: schedule definitions, trigger history.  
  Depends on: Event plane, Nova-lite.

## Environment subsystems

- **State and device layer**  
  Purpose: represent external entities (home devices, services, infrastructure) and their state.  
  Owns: a canonical view of entities and some metadata (future Nova State).  
  Depends on: Home Assistant and other controllers.

- **Voice layer**  
  Purpose: handle speech input and output and route intents into the event plane.  
  Owns: voice pipeline configuration and mappings between voice events and Nova events.  
  Depends on: Home Assistant Assist or equivalent local voice stack, LLM provider.

- **LLM provider layer**  
  Purpose: expose model inference, summarization, and tool-use capabilities behind an abstract interface.  
  Owns: model configuration and routing rules.  
  Depends on: underlying model serving tools (e.g., Ollama).

## Platform subsystems

- **Nova Control**  
  Purpose: main UI/API for configuration, boards, approvals, and status.  
  Owns: settings, registry of services, user roles (as needed).  
  Depends on: nearly all other subsystems.

- **Nova Observe**  
  Purpose: centralized observability and audit trail.  
  Owns: logs, traces, metrics, audit records.  
  Depends on: instrumentation across subsystems.

- **Event plane implementation**  
  Purpose: accept, store, and route events.  
  Owns: event schema, event log, and routing configurations.  
  Depends on: database or message broker infrastructure.

- **Secrets abstraction**  
  Purpose: provide a unified way to access secrets regardless of underlying secret manager.  
  Owns: mapping between logical secrets and backing stores.  
  Depends on: external secret managers or local secret storage.

## Relationship to the capability map

Each capability in the map should correspond to one or more subsystems here. The capability document describes *what* must be possible and which implementation is temporary; this overview describes *where* those capabilities live in the codebase and deployment topology.[web:129][web:231][web:236]

Future subsystem-level specs (Nova-lite, Nova Board, workflows, state, voice, memory, policy, observability, control plane, connectors) should reference both this overview and the capability map to keep design and implementation aligned.
