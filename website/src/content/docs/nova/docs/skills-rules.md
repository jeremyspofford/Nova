---
title: "Skills & Rules"
description: "Planned systems for reusable prompt templates and declarative behavior constraints."
---

import { Aside } from '@astrojs/starlight/components';

<Aside type="caution" title="Coming Soon">
Skills and Rules are planned for Phase 5c of Nova's roadmap. They are not yet implemented. This page describes the intended design.
</Aside>

Skills and Rules make Nova's agents configurable without code changes. **Skills** are reusable prompt templates shared across agents and pods. **Rules** are declarative behavior constraints that complement the Guardrail Agent with user-defined policies and pre-execution enforcement.

## Skills -- Reusable prompt templates

Skills are reusable blocks of prompt text that can be injected into agent system prompts. Instead of duplicating instructions across multiple agents, you define a skill once and assign it to any combination of agents and pods.

### Concepts

| Concept | Description |
|---------|-------------|
| **Content** | The prompt text, optionally with `{{param}}` placeholders for parameterization |
| **Scope** | `global` (all agents), `pod` (agents in specific pods), or `agent` (specific agents only) |
| **Parameters** | Named placeholders with defaults and descriptions, filled at runtime |
| **Category** | Organizational grouping: `workflow`, `coding`, `review`, `safety`, or `custom` |
| **Priority** | Higher priority skills are injected earlier in the system prompt |
| **System skills** | Built-in skills that ship with Nova; visible but not editable |

### How skills are resolved

When an agent runs, the skill resolver collects all applicable skills:

1. **Global skills** -- always included
2. **Pod-scoped skills** -- included if the agent belongs to a matching pod
3. **Agent-scoped skills** -- included if directly assigned to the agent

Skills are ordered by priority (highest first) and formatted as an `## Active Skills` section in the agent's system prompt. The result is cached with a 30-second TTL since skills change rarely.

### Example skill

```
Name:     code-review-checklist
Category: review
Scope:    pod (assigned to "Code Generation" pod)
Content:
  When reviewing code, check for:
  1. Error handling — are all error paths covered?
  2. Security — any injection vectors, credential exposure?
  3. Performance — unnecessary loops, missing indexes?
  4. Testing — are there tests for the changes?
  5. {{custom_check}}

Parameters:
  - custom_check (default: "Documentation — are public APIs documented?")
```

### Planned API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/skills` | List all skills |
| POST | `/api/v1/skills` | Create a skill |
| PATCH | `/api/v1/skills/{id}` | Update a skill |
| DELETE | `/api/v1/skills/{id}` | Delete a skill |
| PUT | `/api/v1/skills/{id}/pods` | Set pod assignments |
| PUT | `/api/v1/skills/{id}/agents` | Set agent assignments |

## Rules -- Declarative behavior constraints

Rules define behavioral boundaries for agents. They complement the Guardrail Agent's built-in checks (prompt injection, PII, credential leak, spec drift) with user-defined policies that can be enforced both before and after tool execution.

### Two enforcement paths

| Enforcement | How it works | When |
|-------------|-------------|------|
| **Soft** | Rule text injected into the Guardrail Agent's system prompt; compliance checked as part of normal LLM review | Post-execution |
| **Hard** | Regex pattern matched against tool calls before execution; blocks the call if matched | Pre-execution |

A rule can use `both` enforcement -- the pattern blocks immediate violations, and the Guardrail Agent catches subtle ones.

### Actions

When a hard rule matches, the configured action determines what happens:

| Action | Behavior |
|--------|----------|
| `block` | Return an error to the LLM; the tool call is not executed |
| `warn` | Execute the tool but log a warning |
| `require_approval` | Pause execution and wait for human approval |

### Planned seed rules

Nova will ship with three built-in system rules:

| Rule | Enforcement | Action | Description |
|------|-------------|--------|-------------|
| `no-rm-rf` | Hard | Block | Prevent recursive force delete commands |
| `workspace-boundary` | Soft | Block | Keep agents within the designated workspace |
| `no-secret-in-output` | Soft | Block | Prevent API keys and secrets in agent responses |

System rules are visible and can be disabled, but cannot be deleted.

### Rule properties

| Property | Description |
|----------|-------------|
| **Name** | Unique identifier |
| **Rule text** | Human-readable description of the constraint |
| **Pattern** | Regex for hard enforcement (optional) |
| **Target tools** | Which tools the pattern applies to (null = all) |
| **Enforcement** | `soft`, `hard`, or `both` |
| **Action** | `block`, `warn`, or `require_approval` |
| **Scope** | `global`, `pod`, or `agent` |
| **Category** | `safety`, `quality`, `compliance`, or `workflow` |
| **Severity** | `low`, `medium`, `high`, or `critical` |

### Planned API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/rules` | List all rules |
| POST | `/api/v1/rules` | Create a rule |
| PATCH | `/api/v1/rules/{id}` | Update a rule |
| DELETE | `/api/v1/rules/{id}` | Delete a rule (system rules cannot be deleted) |

## Dashboard pages

### Skills page

- List all skills with scope badges (global / pod / agent)
- Create and edit with a content editor (markdown-capable textarea)
- Parameter definition UI (name, default, description)
- Pod/agent assignment via multi-select
- System skills shown as non-editable
- Enable/disable toggle

### Rules page

- List all rules with enforcement type and severity badges
- Create and edit with a regex pattern tester (live validation)
- Tool targeting (select which tools the rule applies to)
- System rules shown as non-deletable
- Enable/disable toggle
- "Test rule" button -- paste a sample tool call and see if the rule matches
