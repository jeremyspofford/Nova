# Nova Website Design — nova.arialabs.ai

> **Date:** 2026-03-06
> **Status:** Approved
> **Approach:** Astro + Starlight in monorepo `/website` folder

---

## Overview

A marketing landing page + comprehensive documentation site for Nova, deployed at `nova.arialabs.ai`. Serves three audiences:

1. **Casual users** — understand what Nova does, get excited, install it
2. **Power users / developers** — deep docs, API reference, architecture, configuration
3. **Enterprise (future)** — private, secure, self-hosted AI for dev teams (messaging deferred to v2)

---

## Tech Stack

| Choice | Rationale |
|--------|-----------|
| **Astro** | Static-first, ships near-zero JS, fast, great for marketing pages |
| **Starlight** (Astro plugin) | Docs with built-in search, sidebar nav, dark mode, content collections |
| **Tailwind CSS** | Matches dashboard palette (stone/teal/amber/emerald) |
| **Cloudflare Pages** | Already have Cloudflare integration, free, fast CDN |
| **Monorepo** (`/website`) | Single repo, single CI, content stays close to code |

---

## Project Structure

```
website/
├── astro.config.mjs
├── package.json
├── tailwind.config.mjs
├── src/
│   ├── pages/
│   │   ├── index.astro              # Landing page
│   │   └── changelog.astro          # Changelog listing
│   ├── content/
│   │   ├── docs/                    # Starlight markdown docs
│   │   │   ├── quickstart.md
│   │   │   ├── architecture.md
│   │   │   ├── configuration.md
│   │   │   ├── pipeline.md
│   │   │   ├── inference-backends.md
│   │   │   ├── mcp-tools.md
│   │   │   ├── ide-integration.md
│   │   │   ├── remote-access.md
│   │   │   ├── deployment.md
│   │   │   ├── api-reference.md
│   │   │   ├── security.md
│   │   │   ├── skills-rules.md
│   │   │   ├── roadmap.md
│   │   │   └── services/
│   │   │       ├── orchestrator.md
│   │   │       ├── llm-gateway.md
│   │   │       ├── memory-service.md
│   │   │       ├── chat-api.md
│   │   │       ├── dashboard.md
│   │   │       └── recovery.md
│   │   └── changelog/               # Changelog entries
│   │       ├── 2026-03-06.md
│   │       └── ...
│   ├── components/
│   │   ├── Hero.astro
│   │   ├── FeatureCard.astro
│   │   ├── PipelineDiagram.astro
│   │   ├── InferenceBackends.astro
│   │   ├── ArchitectureDiagram.astro
│   │   └── InstallBlock.astro
│   ├── layouts/
│   │   └── Landing.astro
│   └── styles/
│       └── global.css
├── public/
│   ├── og-image.png
│   └── favicon.svg
```

---

## Page Map

| Route | Type | Purpose |
|-------|------|---------|
| `/` | Landing | Hero, differentiators, pipeline, features, architecture, install |
| `/changelog` | Listing | Shipped features, sorted by date |
| `/docs/` | Starlight | Docs root |
| `/docs/quickstart` | Doc | Install, setup wizard, first run |
| `/docs/architecture` | Doc | Service topology, inter-service communication |
| `/docs/configuration` | Doc | .env, models.yaml, context budgets |
| `/docs/pipeline` | Doc | 5-stage agent pipeline deep-dive |
| `/docs/inference-backends` | Doc | Ollama vs vLLM vs llama.cpp vs SGLang comparison, setup, profiles |
| `/docs/services/*` | Doc | Per-service docs (orchestrator, llm-gateway, memory, chat-api, dashboard, recovery) |
| `/docs/mcp-tools` | Doc | MCP catalog, how to add servers |
| `/docs/ide-integration` | Doc | Cursor, Continue.dev, Aider setup |
| `/docs/remote-access` | Doc | Cloudflare Tunnel + Tailscale setup |
| `/docs/deployment` | Doc | Docker Compose, GPU overlays, remote Ollama, backend selection |
| `/docs/api-reference` | Doc | REST endpoints per service |
| `/docs/security` | Doc | Auth, API keys, sandbox tiers, data privacy |
| `/docs/skills-rules` | Doc | Skills & Rules system |
| `/docs/roadmap` | Doc | Project roadmap |

---

## Landing Page Sections

### 1. Hero

- **Headline:** Communicates autonomy + ownership (e.g., "Your AI, Your Rules" or "Autonomous AI That Runs Where You Do")
- **Subheadline:** One sentence — define a goal, Nova plans, executes, re-plans, completes
- **CTAs:** `Get Started` (scrolls to install) + `Read the Docs`
- Dark, sleek aesthetic matching dashboard stone/teal palette

### 2. Key Differentiators (4 cards)

| Card | Message |
|------|---------|
| **Self-Directed** | Define a goal. Nova breaks it into subtasks, executes autonomously, re-plans as needed. |
| **Self-Improving** | Learns your preferences, customizes itself, updates its own configuration over time. |
| **Private & Secure** | Runs entirely on your hardware. Your data never leaves. Sandbox tiers control what agents can access. |
| **Parallel By Design** | Continuous batching, concurrent pipelines, 4 inference backends. No bottleneck. |

### 3. Pipeline Visual

Full 5-stage pipeline diagram:

```
Context Agent    -->  curates relevant code, docs, history
Task Agent       -->  produces the actual output
Guardrail Agent  -->  prompt injection, PII, credential leak, spec drift
Code Review      -->  pass / needs_refactor / reject (loops back, max 3x)
Decision Agent   -->  ADR artifact + human escalation (on reject)
```

Post-pipeline callout: Documentation, Diagramming, Security Review, Memory Extraction agents run in parallel after main pipeline completes.

### 4. Key Features (expanded grid)

- **4 Inference Backends** — Ollama, vLLM, llama.cpp, SGLang. Pick the right engine for your workload. Run multiple simultaneously.
- **RadixAttention Optimization** — SGLang caches shared agent system prompts across parallel tasks for significant inference speedup.
- **Skills & Rules** — Extensible prompt templates and declarative behavior constraints without code changes.
- **Sandbox Tiers** — isolated / nova / workspace / host execution environments with security-first defaults.
- **MCP Tool Ecosystem** — Plug in any MCP server: GitHub, Slack, Sentry, Playwright, Docker, and more.
- **Self-Configuration** — Nova can modify its own settings, prompts, and pod definitions via the nova sandbox tier.
- **Multi-Provider LLM Routing** — Anthropic, OpenAI, Ollama, Groq, Gemini, Cerebras, OpenRouter, plus subscription-based Claude/ChatGPT at zero API cost.
- **GPU-Aware Setup** — Auto-detects hardware, recommends backends, supports remote GPU over LAN with Wake-on-LAN.
- **Recovery & Resilience** — Backup/restore, factory reset, service health monitoring via dedicated sidecar service.
- **IDE Integration** — OpenAI-compatible endpoint works with Cursor, Continue.dev, Aider, and any OpenAI-API client.

### 5. Architecture Diagram

Clean visual showing:
- 8-service Docker Compose stack
- LLM Gateway with swappable inference backends behind it (not just "Ollama")
- Multiple backends coexisting (e.g., Ollama for model variety + SGLang for production serving)
- Redis task queue connecting orchestrator to pipeline
- Memory service with pgvector

### 6. Install Section

```bash
git clone https://github.com/arialabs/nova.git
cd nova
./setup
```

- Callout: setup wizard auto-detects GPU, offers backend selection, configures everything
- Remote GPU setup: one-liner script for GPU machine
- Link to detailed quickstart docs

### 7. Footer

- GitHub repo link
- Documentation link
- Aria Labs link
- Subtle "Enterprise inquiries" email (placeholder for later)

---

## Changelog Strategy

### Format

Content collection at `website/src/content/changelog/*.md`:

```markdown
---
date: 2026-03-06
version: "0.x.x"  # optional, when versioning starts
---

## Dashboard: Remote Access & Navigation

- Added Remote Access page with Cloudflare Tunnel and Tailscale wizards
- Updated NavBar with new navigation structure
- Expanded MCP server catalog
```

### Process

- One markdown file per release/update, named by date
- Backfill initial entries from git history for launch
- Add new changelog entry with each feature commit going forward
- Auto-sorted by date, paginated by Starlight content collections
- Complements the roadmap: roadmap = what's planned, changelog = what shipped

---

## Design Palette

- **Colors:** stone/teal/amber/emerald — matches dashboard
- **Theme:** Dark-first (most dev tool sites are dark)
- **Typography:** Clean, generous whitespace

---

## What's NOT in v1

- Interactive demo / live sandbox
- Enterprise pricing page
- Blog (can add later as content collection)
- i18n / translations
- Analytics
- Custom search (Starlight built-in is sufficient)

---

## Keeping Content Current

1. **Docs are markdown** — edit a `.md` file, auto-deploys
2. **Landing page features are data-driven** — feature cards defined in an array/data file, not hardcoded HTML. Adding a feature = adding an object.
3. **Changelog captures releases** — each feature gets a dated entry
4. **Roadmap synced** — docs/roadmap.md content flows into the docs site
