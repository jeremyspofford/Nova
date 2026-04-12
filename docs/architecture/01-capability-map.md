# Nova Capability Map

This capability map defines what the Nova suite must do, which implementations are temporary, which future services should own the capability, and where replacement effort should be focused first.[cite:117][cite:122][cite:126][cite:129]

The map is intentionally strategic rather than exhaustive: it exists to prevent the suite from collapsing into a pile of tools and to keep clear boundaries between borrowed infrastructure and future Nova-owned product capabilities.[cite:123][cite:129][cite:131]

## Capability matrix

| Capability | User-facing purpose | Temporary implementation | Future implementation | Internal contract | Strategic value | Replacement priority | Replacement trigger |
|---|---|---|---|---|---|---|---|
| Agent runtime | Proactive and reactive AI behavior, bounded planning, follow-up | Nova-lite MVP or optional OpenClaw-style runtime[cite:64][cite:74] | Nova Core | `agent-runtime` | Very high | High | External runtime blocks product behavior, safety model, or UX[cite:122][cite:128] |
| Workflow execution | Execute automations, jobs, and external tool chains | n8n and Windmill[cite:43][cite:53] | Nova Flow | `workflow-executor` | High | Medium | Need unified orchestration semantics, lower fragility, or deeper product control[cite:117][cite:129] |
| Device/state layer | Read and control home, devices, services, and environment state | Home Assistant[cite:49][cite:52] | Nova State | `state-provider` | High | Medium | Need custom entity model, richer cross-domain state, or tighter coupling to Nova behaviors[cite:120][cite:129] |
| LLM serving | Inference, summarization, planning, routing, tool-call reasoning | Ollama, local model runner, or approved cloud LLM provider[cite:65][cite:391] | Nova Serve or pluggable multi-provider layer | `llm-provider` | Medium | Low | Existing serving cannot satisfy routing, performance, model governance, portability, or local/cloud routing needs[cite:122][cite:131][cite:390] |
| Memory and tasks | Persistent tasks, follow-ups, notes, task state, execution memory | Nova database from day one[cite:93] | Nova Memory | `task-store`, `memory-store` | Very high | High | Early ownership required because persistence is core product behavior[cite:74][cite:93] |
| Voice interface | Speech input/output and assistant interaction | Home Assistant Assist plus local speech stack[cite:17][cite:25] | Nova Voice | `voice-provider` | Medium | Low to medium | Need unified cross-device UX, deeper assistant identity, or tighter multimodal orchestration |
| Task board | Shared work surface for user and Nova, approvals, visible task state | Minimal Nova Board service[cite:176][cite:199] | Nova Board | `task-board` | High | High | Needed for durable human-agent work visibility and approval handling[cite:186][cite:194] |
| Policy and approvals | Safety classes, approvals, guardrails, kill switch | Thin Nova-owned policy layer[cite:92][cite:101] | Nova Policy | `policy-engine` | Very high | High | External tools cannot enforce cross-system safety consistently[cite:101][cite:193] |
| Observability and audit | Logs, traces, task history, decision visibility, metrics | Mixed tool-native logs plus Nova audit DB[cite:76][cite:193] | Nova Observe | `telemetry` | High | Medium | Need unified debugging, trust, and product-grade auditability[cite:92][cite:193] |
| Control plane | Settings, service registry, admin views, approvals, deployment awareness | Minimal Nova Control UI/API | Nova Control | `control-plane` | Very high | High | User experience is fragmented across tool UIs or settings surfaces[cite:113][cite:149] |
| Connectors and adapters | Integrate external apps, services, webhooks, and tools | Tool-native nodes plus Nova adapters[cite:54][cite:56] | Nova Connect SDK | `capability-adapter` | High | Medium | Core integrations require consistency, SDK ownership, or stronger governance[cite:56][cite:122] |
| Scheduler and heartbeat | Re-check tasks, trigger periodic reviews, enable durable loops | Nova-lite scheduler[cite:74][cite:77] | Nova Core scheduler | `scheduler` | Very high | High | Need stronger proactive behavior, better retry semantics, or distributed scheduling[cite:86][cite:95] |
| Event bus | Normalize all triggers and state changes into durable events | Nova event API plus queue/database-backed event log[cite:82][cite:88] | Nova Event Plane | `event-bus` | Very high | High | Event coordination becomes central to all subsystems[cite:95][cite:111] |
| Secrets management | Secure access to credentials and tokens | Existing secret manager integration plus Nova abstraction[cite:136] | Nova Secrets or pluggable secret provider | `secret-provider` | High | Medium | Need better portability, auditing, or local-first security UX |
| Deployment orchestration | Install, start, upgrade, and scale services across modes | Docker Compose initially, optional Kubernetes later[cite:147][cite:156] | Nova Deploy | `deployment-orchestrator` | Medium | Low to medium | Need one-command install, fleet management, or cluster-native operations[cite:134][cite:147] |

## Ownership guidance

The earliest Nova-owned capabilities should be memory/tasks, policy, control plane, event bus, scheduler, and the lightweight task board, because those collectively define how the suite behaves and how users trust it.[cite:74][cite:93][cite:101][cite:129]

Workflow execution, device/state, and connectors can remain partially borrowed longer, as long as they are hidden behind contracts and do not leak too much implementation detail into the user experience.[cite:117][cite:120][cite:122]

LLM serving is important, but it should initially be owned at the provider abstraction layer more than at the raw inference-engine layer unless performance, governance, portability, or local-versus-cloud routing requirements force deeper replacement.[cite:122][cite:128][cite:131][cite:391]

## Replacement strategy

The suite should follow a strangler-style replacement model in which borrowed implementations continue operating behind Nova-owned contracts until a custom replacement is good enough to take over incrementally.[cite:117][cite:118][cite:120][cite:127]

That implies every borrowed subsystem should be wrapped through an internal API boundary, with Nova owning the task records, events, approvals, and audit trail even before it owns execution everywhere.[cite:117][cite:126][cite:129]

## Immediate planning implications

The next architecture documents should define the platform architecture, deployment modes, subsystem boundaries, shared data models, and API contracts around the capability map in this file.[cite:200][cite:202][cite:211]

Those documents should treat Nova-lite and Nova Board as early Nova-owned strategic capabilities, while documenting how Home Assistant, n8n, Windmill, and local model runners plug into the suite as temporary or semi-permanent implementations.[cite:132][cite:137][cite:176]
