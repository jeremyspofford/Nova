# 17 – Diagram Inventory and Generation Plan

This document defines the diagram set for the Nova architecture pack. The goal is to create diagrams that are useful for design, discussion, implementation handoff, and future maintenance.

## Diagram strategy

The system should not rely on one giant “everything” diagram. Instead, diagrams should be layered so that each one answers a specific question.

Recommended categories:
- context diagrams
- container/component diagrams
- deployment diagrams
- sequence diagrams
- ownership/evolution diagrams

The preferred authoring format is Mermaid so diagrams can live alongside the markdown architecture documents and stay versionable.

---

## Diagram set

## 17.1 System context diagram

### Goal
Show Nova Suite as a platform in relation to:
- user
- Home Assistant
- local LLMs
- cloud LLMs
- n8n
- Windmill
- external APIs/services
- devices and home systems

### Key question answered
What is Nova, and what does it sit between?

### Best source docs
- 00-suite-vision
- 01-capability-map
- 02-04-platform-deployment-subsystems

---

## 17.2 Platform container diagram

### Goal
Show the major Nova-owned system parts:
- Nova-lite
- Nova Board
- workflow layer
- state layer
- connectors layer
- LLM provider layer
- voice layer
- policy and approvals
- observability
- storage

### Key question answered
What are the main internal building blocks of the platform?

### Best source docs
- 02-04-platform-deployment-subsystems
- 15-16-data-models-and-apis

---

## 17.3 Deployment diagram

### Goal
Show where components run across:
- local mini PC
- AI workstation / GPU box
- optional cloud environment
- home network and edge services

### Key question answered
Where does each major service live in local-only and hybrid modes?

### Best source docs
- 03 deployment modes section
- capability map

---

## 17.4 Sequence diagram: voice/home action

### Goal
Show the flow from user request to provider routing to device action to response.

### Candidate flow
1. user speaks or types
2. voice/input layer creates event
3. Nova-lite interprets intent
4. LLM provider layer selects local or cloud model
5. task is created or resolved directly
6. tool/action is invoked
7. Home Assistant or workflow adapter performs action
8. result is recorded and returned

### Key question answered
How does a real assistant request flow through the system?

---

## 17.5 Sequence diagram: task orchestration flow

### Goal
Show a non-voice workflow, such as CI failure or webhook event becoming a tracked task.

### Candidate flow
1. external event arrives
2. events API receives it
3. task is created
4. board reflects task
5. Nova-lite plans or triages
6. workflow/tool runs
7. run result updates task
8. board and audit state update

### Key question answered
How does Nova turn raw events into managed work?

---

## 17.6 Sequence diagram: approval flow

### Goal
Show a high-risk action requiring approval.

### Candidate flow
1. Nova-lite selects action
2. policy marks it approval-required
3. approval record is created
4. board/UI surfaces approval request
5. user approves or denies
6. run proceeds or is cancelled
7. audit trail is updated

### Key question answered
How is safety enforced without losing automation?

---

## 17.7 Sequence diagram: hybrid LLM routing

### Goal
Show local-first but cloud-optional model selection.

### Candidate flow
1. Nova-lite requests inference
2. provider router checks privacy preference
3. router checks capability requirement
4. local provider is attempted when allowed/preferred
5. cloud provider may be selected when explicitly allowed or required
6. response is returned with provider metadata

### Key question answered
How does Nova stay local-first without becoming local-only?

---

## 17.8 Ownership and evolution diagram

### Goal
Show which parts are:
- Nova-owned now
- borrowed for now
- future replacement candidates

### Key question answered
What is the staged product strategy over time?

### Best source docs
- 01-capability-map
- 04 subsystems overview

---

## Diagram authoring order

Recommended order:
1. system context
2. container diagram
3. deployment diagram
4. task orchestration sequence
5. voice/home sequence
6. approval sequence
7. hybrid LLM routing sequence
8. ownership/evolution diagram

This order ensures that broad structure is established before detailed flows are illustrated.

---

## Deliverable plan

The next diagram deliverable should likely be a single markdown file such as:
- `18-diagrams-mermaid.md`

That file can contain:
- all Mermaid source blocks
- section labels matching the inventory above
- short explanatory text above each diagram

Later, if needed, those Mermaid diagrams can be rendered into PNG or SVG exports for slides or presentations.

---

## Diagram quality rules

- Each diagram should answer one clear question.
- Avoid giant unreadable “all-in-one” diagrams.
- Use consistent subsystem names from the architecture pack.
- Reflect local-first, cloud-optional model routing.
- Show approval and audit paths explicitly.
- Keep adapters and provider abstractions visible.
- Show borrowed versus owned layers clearly where relevant.

This document is the blueprint for producing the actual diagram source in the next step.
