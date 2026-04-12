# 18 – Architecture Diagrams (Mermaid Source)

This document contains Mermaid source for the core Nova architecture diagrams. Diagrams are organized to mirror the diagram inventory.

---

## 18.1 System context diagram

```mermaid
C4Context
    title Nova Suite – System Context

    Person(user, "User", "Person using Nova for home and work automation")

    System_Boundary(nova, "Nova Suite") {
      System(nova_board, "Nova Board", "Task board, approvals, and human-facing workflow control")
      System(nova_lite, "Nova-lite", "Planning, reasoning, and orchestration loop")
      System(nova_api, "Nova APIs", "Events, tasks, tools, runs, entities, LLM routing")
      System(state_layer, "State Layer", "Entity sync from Home Assistant and other systems")
      System(workflow_layer, "Workflow Layer", "Adapters to n8n, Windmill, and future Nova Flow")
      System(llm_layer, "LLM Provider Layer", "Local-first, cloud-optional model access")
      System(voice_layer, "Voice & Input", "Voice and chat entrypoints into Nova")
    }

    System_Ext(ha, "Home Assistant", "Home automation hub and state store")
    System_Ext(n8n, "n8n", "Workflow automation platform")
    System_Ext(windmill, "Windmill", "Script-oriented job/workflow engine")
    System_Ext(local_llm, "Local LLM Runner", "On-device model serving (e.g., Ollama)")
    System_Ext(cloud_llm, "Cloud LLM APIs", "Optional cloud model providers")
    System_Ext(ext_services, "External Services", "APIs, CI/CD, repos, SaaS tools")

    Rel(user, voice_layer, "Speaks to / types into")
    Rel(user, nova_board, "Reviews tasks, approves actions, triggers flows")

    Rel(voice_layer, nova_api, "Creates events and/or tasks")
    Rel(ha, state_layer, "Push/pull entity state, events")
    Rel(state_layer, nova_api, "Emits events, updates entities")

    Rel(nova_board, nova_api, "Reads/writes tasks, approvals, runs")
    Rel(nova_lite, nova_api, "Reads events, tasks; triggers tools, LLM routing")
    Rel(workflow_layer, nova_api, "Translates runs and tools to external workflows")

    Rel(workflow_layer, n8n, "Start workflows, receive callbacks")
    Rel(workflow_layer, windmill, "Start jobs, receive callbacks")

    Rel(llm_layer, local_llm, "Route local-first requests")
    Rel(llm_layer, cloud_llm, "Route cloud-allowed requests")

    Rel(nova_api, ext_services, "Webhooks, API calls, CI/CD, repos, SaaS")
```

---

## 18.2 Platform container diagram

```mermaid
C4Container
    title Nova Suite – Container View

    Person(user, "User")

    System_Boundary(nova, "Nova Suite") {
      Container(nova_api, "Nova API Gateway", "HTTP/JSON", "Events, tasks, tools, runs, entities, providers")

      Container(nova_lite, "Nova-lite", "Service", "Planner/agent loop using events, tasks, tools, and LLM provider")
      Container(nova_board, "Nova Board", "Web UI / Service", "Board, approvals, task management")
      Container(state_svc, "State Service", "Service", "Entity sync with Home Assistant and others")
      Container(workflow_adapter, "Workflow Adapter", "Service", "Bridges tools/runs to n8n, Windmill, future Nova Flow")
      Container(llm_provider, "LLM Provider Service", "Service", "Local-first model routing, cloud-optional")
      Container(voice_gateway, "Voice & Input Gateway", "Service", "Speech-to-text, text, and intent events into Nova")
      Container(policy_svc, "Policy & Approvals", "Service", "Rules for risk, approvals, and escalation")
      Container(obs_svc, "Observability Service", "Service", "Metrics, traces, logs, event streams")

      ContainerDb(core_db, "Core DB", "SQL/Document", "Tasks, events, runs, approvals, entities, provider profiles")
    }

    System_Ext(ha, "Home Assistant")
    System_Ext(n8n, "n8n")
    System_Ext(windmill, "Windmill")
    System_Ext(local_llm, "Local LLM Runner")
    System_Ext(cloud_llm, "Cloud LLM APIs")
    System_Ext(ext_services, "External Services")

    Rel(user, nova_board, "View tasks, approve, trigger")
    Rel(user, voice_gateway, "Speak/type requests")

    Rel(voice_gateway, nova_api, "POST events/tasks")
    Rel(nova_board, nova_api, "GET/POST/PATCH tasks, approvals, runs")
    Rel(nova_lite, nova_api, "Poll/subscribe events, update tasks, invoke tools, route LLM")

    Rel(nova_api, state_svc, "Sync entities, events")
    Rel(state_svc, ha, "Read/write entities, receive events")

    Rel(nova_api, workflow_adapter, "Invoke tools mapped to workflows/jobs")
    Rel(workflow_adapter, n8n, "Start workflows, receive webhooks")
    Rel(workflow_adapter, windmill, "Start jobs, receive callbacks")

    Rel(nova_api, llm_provider, "Route LLM calls")
    Rel(llm_provider, local_llm, "Local-first inference")
    Rel(llm_provider, cloud_llm, "Cloud-optional inference")

    Rel(nova_api, policy_svc, "Check risk and approval requirements")
    Rel(policy_svc, nova_board, "Surface approval requests")

    Rel(nova_api, core_db, "Read/write all core records")
    Rel(obs_svc, core_db, "Read events/runs for observability")
    Rel(nova_api, obs_svc, "Emit metrics, traces, logs")

    Rel(nova_api, ext_services, "Webhooks, outbound API calls")
```

---

## 18.3 Deployment diagram

```mermaid
C4Deployment
    title Nova Suite – Deployment View (Local-first, Cloud-optional)

    Deployment_Node(home_net, "Home Network") {
      Deployment_Node(mini_pc, "Mini PC", "Docker/Compose or K8s") {
        Container(nova_api, "Nova API Gateway")
        Container(nova_lite, "Nova-lite")
        Container(nova_board, "Nova Board")
        Container(state_svc, "State Service")
        Container(workflow_adapter, "Workflow Adapter")
        Container(llm_provider, "LLM Provider Service")
        Container(voice_gateway, "Voice & Input Gateway")
        Container(policy_svc, "Policy & Approvals")
        Container(obs_svc, "Observability Service")
        ContainerDb(core_db, "Core DB")
      }

      Deployment_Node(ai_box, "AI Workstation / GPU Box", "Optional") {
        Container(local_llm, "Local LLM Runner")
      }

      Deployment_Node(home_assistant_node, "Home Assistant Host") {
        System(ha, "Home Assistant")
      }
    }

    Deployment_Node(cloud, "Optional Cloud / Remote") {
      Deployment_Node(cloud_env, "Cloud Environment") {
        System(n8n, "n8n (cloud or self-hosted)")
        System(windmill, "Windmill (cloud or self-hosted)")
        System(cloud_llm, "Cloud LLM Providers")
        System(ext_services, "External APIs / SaaS / CI/CD")
      }
    }

    Rel(voice_gateway, nova_api, "Internal network")
    Rel(nova_board, nova_api, "Internal network")
    Rel(nova_api, core_db, "Local DB access")

    Rel(nova_api, state_svc, "Local call")
    Rel(state_svc, ha, "Home network, HTTP or integrations")

    Rel(llm_provider, local_llm, "Local call / gRPC / HTTP")
    Rel(llm_provider, cloud_llm, "Outbound HTTPS (cloud-optional)")

    Rel(workflow_adapter, n8n, "Outbound HTTPS or VPN")
    Rel(workflow_adapter, windmill, "Outbound HTTPS or VPN")

    Rel(nova_api, ext_services, "Outbound HTTPS / webhooks")
```

---

## 18.4 Sequence – task orchestration flow

```mermaid
sequenceDiagram
    title Task orchestration from external event

    participant Ext as External Service
    participant HA as Home Assistant
    participant NovaAPI as Nova API
    participant State as State Service
    participant NovaLite as Nova-lite
    participant Board as Nova Board
    participant WF as Workflow Adapter
    participant Runs as Runs Store

    Ext->>NovaAPI: POST /events (e.g., CI failure)
    NovaAPI->>NovaAPI: Persist Event
    NovaAPI->>NovaAPI: Create Task (status=inbox)
    NovaAPI-->>Board: Notify new task (poll/websocket)

    NovaLite->>NovaAPI: Fetch new tasks/events
    NovaLite->>NovaLite: Plan next action
    alt Needs approval
        NovaLite->>NovaAPI: POST /tasks/{id}/approvals
        NovaAPI-->>Board: Surface approval request
        Board->>User: Show approval UI
        User->>Board: Approve or deny
        Board->>NovaAPI: POST /approvals/{id}/respond
    end

    opt Requires workflow
        NovaLite->>NovaAPI: POST /tools/{name}/invoke (mapped to workflow)
        NovaAPI->>WF: Start external workflow/job
        WF-->>Runs: Record Run (status=running)
        WF-->>NovaAPI: Callback on completion/failure
        NovaAPI->>Runs: Update Run
    end

    NovaAPI->>NovaAPI: Update Task status/result_summary
    NovaAPI-->>Board: Board reflects updated task and runs
```

---

## 18.5 Sequence – voice/home action flow

```mermaid
sequenceDiagram
    title Voice/home assistant request

    participant User
    participant Voice as Voice Gateway
    participant NovaAPI as Nova API
    participant NovaLite as Nova-lite
    participant LLM as LLM Provider
    participant HA as Home Assistant
    participant State as State Service

    User->>Voice: Speak request ("turn on porch light and set 15m timer")
    Voice->>LLM: Transcribe + interpret (optional local/cloud model)
    Voice->>NovaAPI: POST /events (voice.command.received)

    NovaLite->>NovaAPI: Fetch recent events/tasks
    NovaLite->>LLM: Route reasoning request via LLM Provider
    LLM-->>NovaLite: Parsed intent and suggested actions

    NovaLite->>NovaAPI: Create or update Task
    NovaLite->>NovaAPI: Invoke Home Assistant tool via /tools
    NovaAPI->>HA: Call service (e.g., light.turn_on, timer.start)

    HA-->>State: Update entity state
    State-->>NovaAPI: Emit new Event + Entity update
    NovaAPI-->>NovaLite: Event feed or poll

    NovaLite->>NovaAPI: Mark task done, add result_summary
    NovaAPI-->>Voice: Optional feedback payload (for TTS)
    Voice-->>User: "Porch light is on and a 15-minute timer is set."
```

---

## 18.6 Sequence – approval flow

```mermaid
sequenceDiagram
    title Approval for high-risk action

    participant NovaLite as Nova-lite
    participant Policy as Policy Service
    participant NovaAPI as Nova API
    participant Board as Nova Board
    participant User
    participant WF as Workflow Adapter

    NovaLite->>Policy: Evaluate planned action (risk, approval)
    Policy-->>NovaLite: Requires approval

    NovaLite->>NovaAPI: POST /tasks/{id}/approvals
    NovaAPI-->>Board: New approval request visible

    Board->>User: Show request + consequences
    User->>Board: Approve/Deny + reason
    Board->>NovaAPI: POST /approvals/{id}/respond

    NovaAPI->>NovaLite: Approval decision via event/task update

    alt Approved
        NovaLite->>NovaAPI: Invoke corresponding tool/workflow
        NovaAPI->>WF: Start workflow/run
    else Denied
        NovaLite->>NovaAPI: Mark task failed or deferred
    end
```

---

## 18.7 Sequence – hybrid LLM routing

```mermaid
sequenceDiagram
    title Local-first, cloud-optional LLM routing

    participant NovaLite as Nova-lite
    participant LLMRouter as LLM Provider Service
    participant Local as Local LLM Runner
    participant Cloud as Cloud LLM Provider

    NovaLite->>LLMRouter: Request inference (purpose, input, prefs)

    LLMRouter->>LLMRouter: Check privacy_preference
    LLMRouter->>LLMRouter: Check provider capabilities and health

    alt local_required
        LLMRouter->>Local: Inference request
        Local-->>LLMRouter: Output or error
    else local_preferred
        LLMRouter->>Local: Try local inference
        alt local fails or insufficient
            LLMRouter->>Cloud: Fallback (only if cloud_allowed)
            Cloud-->>LLMRouter: Output
        end
    else cloud_allowed only
        LLMRouter->>Cloud: Inference request
        Cloud-->>LLMRouter: Output
    end

    LLMRouter-->>NovaLite: Output + provider metadata
```

---

## 18.8 Ownership and evolution diagram

```mermaid
flowchart LR
    subgraph OwnedNow[Owned Now]
        direction TB
        A[Nova-lite]
        B[Nova Board]
        C[Core API & Data Models]
        D[LLM Provider Abstraction]
        E[Policy & Approvals]
        F[Observability Integration]
    end

    subgraph BorrowedNow[Borrowed Now]
        direction TB
        G[Home Assistant]
        H[n8n]
        I[Windmill]
        J[Local LLM Runner]
        K[Cloud LLM Providers]
    end

    subgraph FutureReplacement[Future Replacement Candidates]
        direction TB
        L[Nova Flow]
        M[Nova State]
        N[Native Connectors]
    end

    A --> C
    B --> C
    D --> J
    D --> K

    C --> G
    C --> H
    C --> I

    H --> L
    I --> L
    G --> M

    C --> N
```
