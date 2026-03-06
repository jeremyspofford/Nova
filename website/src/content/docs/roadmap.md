---
title: "Roadmap"
description: "Nova's development roadmap -- completed phases and upcoming work."
---

Nova is under active development. This page summarizes the major phases of the project. For the full internal roadmap with implementation details, see the [docs/roadmap.md](https://github.com/arialabs/nova/blob/main/docs/roadmap.md) file in the repository.

## Vision

A self-directed autonomous AI platform. You define a goal. Nova breaks it into subtasks, executes them through a coordinated pipeline of specialized agents with built-in safety rails, evaluates its own progress, re-plans as needed, and completes the goal -- with minimal human intervention except when it genuinely needs a decision.

## Autonomy levels

| Level | Description | Status |
|-------|-------------|--------|
| **1 -- Pipeline autonomy** | Quartet runs all agents without human input; escalates only on critical flags | Implemented |
| **2 -- Async execution** | Tasks run in the background; submit and come back | Implemented |
| **3 -- Triggered execution** | Tasks start from external events -- git push, cron, webhook, Slack | Planned |
| **4 -- Self-directed** | Nova breaks goals into subtasks, executes, evaluates, re-plans, loops to completion | Planned |

## Completed phases

### Phase 1 -- Core Platform

The foundation: containerized microservices communicating over HTTP. Multi-turn agent loop with tool use, streaming responses via SSE and WebSocket, pluggable tool system, and 39+ registered model IDs.

### Phase 2 -- Auth, Billing & IDE Integration

API key authentication (SHA-256 hashed, `sk-nova-*` format), per-key rate limiting via Redis, admin-only endpoints, PostgreSQL storage for keys and usage events, token counting and cost tracking, and OpenAI-compatible endpoints for IDE integration (Continue.dev, Cursor, Aider).

### Phase 3 -- Code & Terminal Tools

Workspace-scoped file I/O (`list_dir`, `read_file`, `write_file`), shell execution with timeout and denylist, ripgrep code search, git operations, path traversal protection, and Docker workspace volume mounting. Includes sandbox tier design (isolated/nova/workspace/host).

### Phase 4 -- Quartet Pipeline & Async Queue

The 5-stage agent pipeline (Context, Task, Guardrail, Code Review, Decision), Redis BRPOP task queue with heartbeat and stale reaper, 11-state task state machine, human-in-the-loop review, clarification requests, pod and agent configuration (per-agent model, tools, system prompt, run conditions), and subscription-based LLM providers (Claude Max, ChatGPT Plus) for zero-cost operation.

### Phase 5 -- Dashboard

React admin UI with Overview, Chat, Usage, Keys, Models, Tasks, Pods, MCP, Memory Inspector, Agent Endpoints, Settings, Recovery, and Remote Access pages. Built with Vite, Tailwind CSS, TanStack Query, and Recharts.

### Phase 5.5 -- Hardening

Operational maturity improvements: fixed MCP tool visibility for agents, test foundation (pytest), streaming token count fixes, reaper race condition fix, structured JSON logging across all services, 3-tier embedding cache, and working memory cleanup.

### Phase 6 -- Memory Overhaul

Three-tier memory architecture (semantic, procedural, episodic) with hybrid retrieval (70% cosine similarity + 30% ts_rank), ACT-R confidence decay, fact upserts, embedding fallback chain, and Memory Inspector dashboard page.

## Current and upcoming

### Phase 5c -- Skills & Rules (planned)

Reusable prompt templates (skills) shared across agents/pods, and declarative behavior constraints (rules) with soft (LLM-based) and hard (pre-execution regex) enforcement. See [Skills & Rules](/skills-rules/) for details.

### Phase 6c -- SDK, CLI/TUI & Documentation (planned)

Typed Python SDK (`nova-sdk`), CLI with Typer + Rich (`nova-cli`), interactive TUI with Textual, auto-generated TypeScript types from Pydantic contracts, and a comprehensive documentation system.

### Phase 7 -- Self-Directed Autonomy (planned)

Planning Agent that decomposes goals into subtask DAGs, executes them through the pipeline, evaluates results, and re-plans. This is the core of Nova's autonomous operation.

### Phase 9 -- Triggered Execution (planned)

External event triggers: git webhooks, cron schedules, Slack commands, and custom webhook endpoints that automatically submit tasks to the pipeline.

### Phase 9b -- Integrated Web IDE (planned)

Browser-based code editor with git workspace management, integrated with Nova's agent pipeline for AI-assisted development.

### Phase 10 -- Edge Computing (planned)

Edge deployment capabilities for running Nova agents closer to data sources and event triggers.

### Phase 11 -- Multi-Cloud (planned)

Multi-cloud deployment support for distributing Nova across cloud providers.

### Phase 12 -- Inference Backends (planned)

Multiple local inference backends (Ollama, vLLM, llama.cpp, SGLang) for concurrent serving, GPU upgrade path, and optimized multi-user performance.

### Phase 13 -- Multi-Tenancy (planned)

User isolation for multi-person deployments: separate chat histories, memory spaces, API keys, preferences, and usage tracking. Includes authentication, role-based access, and per-user data scoping.

### Phase 14 -- SaaS & Hosted Offering (planned)

Nova Cloud at `nova.arialabs.ai` -- a hosted version where users sign up and use Nova without self-hosting. Three tiers (Free, Pro, Enterprise), Stripe billing, Kubernetes infrastructure, and full data portability between SaaS and self-hosted. Builds on Phase 12 (concurrent inference) and Phase 13 (multi-tenancy).

## Contributing

Nova is open source. Check the full [roadmap](https://github.com/arialabs/nova/blob/main/docs/roadmap.md) for detailed implementation plans, or dive into the codebase to start contributing.
