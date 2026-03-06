# Nova Website Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and deploy the Nova marketing + docs website at `nova.arialabs.ai` using Astro + Starlight.

**Architecture:** Astro static site with Starlight docs plugin in `/website` monorepo folder. Custom landing page at `/`, Starlight-powered docs at `/docs/`, changelog via content collection. Dark-first design matching dashboard stone/teal/amber/emerald palette. Deployed to Cloudflare Pages.

**Tech Stack:** Astro 5, @astrojs/starlight, Tailwind CSS v4 (@tailwindcss/vite), TypeScript

**Design doc:** `docs/plans/2026-03-06-website-design.md`

---

### Task 1: Scaffold Astro + Starlight Project

**Files:**
- Create: `website/package.json`
- Create: `website/astro.config.mjs`
- Create: `website/tsconfig.json`
- Create: `website/src/styles/global.css`
- Create: `website/src/content.config.ts`
- Create: `website/src/content/docs/index.md` (placeholder)
- Modify: `.gitignore` (add `website/node_modules`, `website/dist`, `website/.astro`)

**Step 1: Create the project using Starlight Tailwind template**

```bash
cd /home/jeremy/workspace/nova
npm create astro@latest -- website --template starlight/tailwind --no-install --no-git
```

If the template scaffolds interactively, use manual setup instead:

```bash
mkdir -p website
cd website
npm init -y
npm install astro @astrojs/starlight @tailwindcss/vite tailwindcss
```

**Step 2: Configure `website/astro.config.mjs`**

```javascript
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  site: 'https://nova.arialabs.ai',
  integrations: [
    starlight({
      title: 'Nova',
      logo: {
        light: './src/assets/nova-logo-light.svg',
        dark: './src/assets/nova-logo-dark.svg',
        replacesTitle: false,
      },
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/arialabs/nova' },
      ],
      customCss: ['./src/styles/global.css'],
      sidebar: [
        { label: 'Quick Start', slug: 'docs/quickstart' },
        {
          label: 'Core Concepts',
          items: [
            { slug: 'docs/architecture' },
            { slug: 'docs/pipeline' },
            { slug: 'docs/configuration' },
          ],
        },
        {
          label: 'Services',
          autogenerate: { directory: 'docs/services' },
        },
        {
          label: 'Guides',
          items: [
            { slug: 'docs/inference-backends' },
            { slug: 'docs/deployment' },
            { slug: 'docs/remote-access' },
            { slug: 'docs/ide-integration' },
            { slug: 'docs/mcp-tools' },
            { slug: 'docs/skills-rules' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { slug: 'docs/api-reference' },
            { slug: 'docs/security' },
            { slug: 'docs/roadmap' },
          ],
        },
      ],
    }),
  ],
  vite: { plugins: [tailwindcss()] },
});
```

**Step 3: Configure `website/src/styles/global.css`**

```css
@import 'tailwindcss';

/* Stone/teal palette overrides for Starlight */
:root {
  --sl-color-accent-low: #0d3b3b;
  --sl-color-accent: #0d9488;
  --sl-color-accent-high: #5eead4;
  --sl-color-white: #fafaf9;
  --sl-color-gray-1: #e7e5e4;
  --sl-color-gray-2: #d6d3d1;
  --sl-color-gray-3: #a8a29e;
  --sl-color-gray-4: #57534e;
  --sl-color-gray-5: #292524;
  --sl-color-gray-6: #1c1917;
  --sl-color-black: #0c0a09;
}

:root[data-theme='light'] {
  --sl-color-accent-low: #ccfbf1;
  --sl-color-accent: #0d9488;
  --sl-color-accent-high: #134e4a;
}
```

**Step 4: Configure `website/src/content.config.ts`**

```typescript
import { defineCollection, z } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

const docs = defineCollection({
  loader: docsLoader(),
  schema: docsSchema(),
});

const changelog = defineCollection({
  loader: docsLoader(),
  schema: docsSchema({
    extend: z.object({
      date: z.coerce.date(),
      version: z.string().optional(),
    }),
  }),
});

export const collections = { docs, changelog };
```

**Step 5: Create placeholder docs index**

Create `website/src/content/docs/index.md`:

```markdown
---
title: Nova Documentation
description: Docs for the Nova autonomous AI platform.
template: splash
hero:
  tagline: Self-directed autonomous AI that runs where you do.
  actions:
    - text: Quick Start
      link: /docs/quickstart/
      icon: right-arrow
    - text: GitHub
      link: https://github.com/arialabs/nova
      variant: minimal
      icon: external
---
```

**Step 6: Update `.gitignore`**

Append to `.gitignore`:

```
# Website
website/node_modules/
website/dist/
website/.astro/
```

**Step 7: Install dependencies and verify dev server starts**

```bash
cd /home/jeremy/workspace/nova/website
npm install
npx astro dev --port 4000
```

Expected: Dev server starts on `http://localhost:4000`, shows Starlight docs page with teal accent colors.

**Step 8: Verify build**

```bash
cd /home/jeremy/workspace/nova/website
npx astro build
```

Expected: `dist/` folder created, no errors.

**Step 9: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/ .gitignore
git commit -m "Scaffold Nova website with Astro + Starlight + Tailwind"
```

---

### Task 2: Landing Page Layout & Hero

**Files:**
- Create: `website/src/layouts/Landing.astro`
- Create: `website/src/components/Hero.astro`
- Create: `website/src/pages/index.astro`
- Create: `website/src/assets/nova-logo-light.svg` (placeholder)
- Create: `website/src/assets/nova-logo-dark.svg` (placeholder)

**Step 1: Create the Landing layout**

Create `website/src/layouts/Landing.astro` — a standalone HTML layout not using Starlight's template (since this is a custom marketing page):

```astro
---
interface Props {
  title: string;
  description: string;
}

const { title, description } = Astro.props;
---

<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content={description} />
    <title>{title}</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  </head>
  <body class="min-h-screen bg-stone-950 text-stone-100 antialiased">
    <slot />
  </body>
</html>
```

**Step 2: Create placeholder logo SVGs**

Create `website/src/assets/nova-logo-light.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 24" fill="none">
  <text x="0" y="18" font-family="system-ui" font-size="18" font-weight="700" fill="#0c0a09">Nova</text>
</svg>
```

Create `website/src/assets/nova-logo-dark.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 24" fill="none">
  <text x="0" y="18" font-family="system-ui" font-size="18" font-weight="700" fill="#fafaf9">Nova</text>
</svg>
```

**Step 3: Create Hero component**

Create `website/src/components/Hero.astro`:

```astro
---
// Hero section for landing page
---

<section class="relative overflow-hidden px-6 py-24 sm:py-32 lg:py-40">
  <div class="mx-auto max-w-4xl text-center">
    <h1 class="text-4xl font-bold tracking-tight text-stone-50 sm:text-6xl lg:text-7xl">
      Autonomous AI That Runs
      <span class="text-teal-400"> Where You Do</span>
    </h1>
    <p class="mt-6 text-lg leading-8 text-stone-400 max-w-2xl mx-auto">
      Define a goal. Nova breaks it into subtasks, executes them through a
      coordinated pipeline of specialized agents, evaluates progress, re-plans,
      and completes — with minimal human intervention.
    </p>
    <div class="mt-10 flex items-center justify-center gap-x-4">
      <a
        href="#install"
        class="rounded-lg bg-teal-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-teal-500 transition-colors"
      >
        Get Started
      </a>
      <a
        href="/docs/quickstart/"
        class="rounded-lg border border-stone-700 px-6 py-3 text-sm font-semibold text-stone-300 hover:border-stone-500 hover:text-stone-100 transition-colors"
      >
        Read the Docs
      </a>
    </div>
  </div>

  <!-- Subtle gradient glow -->
  <div class="absolute inset-0 -z-10 overflow-hidden">
    <div class="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] rounded-full bg-teal-900/20 blur-3xl"></div>
  </div>
</section>
```

**Step 4: Create the landing page**

Create `website/src/pages/index.astro`:

```astro
---
import Landing from '../layouts/Landing.astro';
import Hero from '../components/Hero.astro';
---

<Landing title="Nova — Autonomous AI Platform" description="Self-directed autonomous AI that runs on your hardware. Private, secure, extensible.">
  <nav class="flex items-center justify-between px-6 py-4 max-w-7xl mx-auto">
    <a href="/" class="text-xl font-bold text-stone-50">Nova</a>
    <div class="flex items-center gap-6">
      <a href="/docs/quickstart/" class="text-sm text-stone-400 hover:text-stone-200 transition-colors">Docs</a>
      <a href="/changelog/" class="text-sm text-stone-400 hover:text-stone-200 transition-colors">Changelog</a>
      <a href="https://github.com/arialabs/nova" target="_blank" rel="noopener noreferrer" class="text-sm text-stone-400 hover:text-stone-200 transition-colors">GitHub</a>
    </div>
  </nav>

  <Hero />
</Landing>
```

**Step 5: Verify the landing page renders**

```bash
cd /home/jeremy/workspace/nova/website
npx astro dev --port 4000
```

Visit `http://localhost:4000/`. Expected: dark landing page with hero, teal accent, two CTA buttons, nav bar.

**Step 6: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/src/layouts/ website/src/components/Hero.astro website/src/pages/index.astro website/src/assets/
git commit -m "Add landing page layout and hero section"
```

---

### Task 3: Differentiators & Features Sections

**Files:**
- Create: `website/src/components/FeatureCard.astro`
- Create: `website/src/data/features.ts`
- Modify: `website/src/pages/index.astro`

**Step 1: Create the feature data file**

Create `website/src/data/features.ts` — data-driven so adding features is just adding an object:

```typescript
export interface Feature {
  title: string;
  description: string;
  icon: string; // Lucide icon name or emoji fallback
}

export const differentiators: Feature[] = [
  {
    title: 'Self-Directed',
    description: 'Define a goal. Nova breaks it into subtasks, executes autonomously, re-plans as needed.',
    icon: 'brain',
  },
  {
    title: 'Self-Improving',
    description: 'Learns your preferences, customizes itself, updates its own configuration over time.',
    icon: 'sparkles',
  },
  {
    title: 'Private & Secure',
    description: 'Runs entirely on your hardware. Your data never leaves. Sandbox tiers control what agents can access.',
    icon: 'shield',
  },
  {
    title: 'Parallel By Design',
    description: 'Continuous batching, concurrent pipelines, 4 inference backends. No bottleneck.',
    icon: 'layers',
  },
];

export const features: Feature[] = [
  {
    title: '4 Inference Backends',
    description: 'Ollama, vLLM, llama.cpp, SGLang. Pick the right engine for your workload. Run multiple simultaneously.',
    icon: 'server',
  },
  {
    title: 'RadixAttention Optimization',
    description: 'SGLang caches shared agent system prompts across parallel tasks for significant inference speedup.',
    icon: 'zap',
  },
  {
    title: 'Skills & Rules',
    description: 'Extensible prompt templates and declarative behavior constraints without code changes.',
    icon: 'puzzle',
  },
  {
    title: 'Sandbox Tiers',
    description: 'Isolated, nova, workspace, host — execution environments with security-first defaults.',
    icon: 'box',
  },
  {
    title: 'MCP Tool Ecosystem',
    description: 'Plug in any MCP server: GitHub, Slack, Sentry, Playwright, Docker, and more.',
    icon: 'plug',
  },
  {
    title: 'Multi-Provider LLM Routing',
    description: 'Anthropic, OpenAI, Ollama, Groq, Gemini, Cerebras, OpenRouter, plus subscription-based Claude/ChatGPT.',
    icon: 'route',
  },
  {
    title: 'GPU-Aware Setup',
    description: 'Auto-detects hardware, recommends backends, supports remote GPU over LAN with Wake-on-LAN.',
    icon: 'cpu',
  },
  {
    title: 'Recovery & Resilience',
    description: 'Backup/restore, factory reset, service health monitoring via dedicated sidecar service.',
    icon: 'refresh-cw',
  },
  {
    title: 'IDE Integration',
    description: 'OpenAI-compatible endpoint works with Cursor, Continue.dev, Aider, and any OpenAI-API client.',
    icon: 'code',
  },
  {
    title: 'Self-Configuration',
    description: 'Nova can modify its own settings, prompts, and pod definitions via the nova sandbox tier.',
    icon: 'settings',
  },
];
```

**Step 2: Create the FeatureCard component**

Create `website/src/components/FeatureCard.astro`:

```astro
---
interface Props {
  title: string;
  description: string;
}

const { title, description } = Astro.props;
---

<div class="rounded-xl border border-stone-800 bg-stone-900/50 p-6 hover:border-stone-700 transition-colors">
  <h3 class="text-base font-semibold text-stone-100">{title}</h3>
  <p class="mt-2 text-sm leading-6 text-stone-400">{description}</p>
</div>
```

**Step 3: Add differentiators and features sections to landing page**

Modify `website/src/pages/index.astro` — add imports and sections after the Hero:

```astro
---
import Landing from '../layouts/Landing.astro';
import Hero from '../components/Hero.astro';
import FeatureCard from '../components/FeatureCard.astro';
import { differentiators, features } from '../data/features';
---

<Landing title="Nova — Autonomous AI Platform" description="Self-directed autonomous AI that runs on your hardware. Private, secure, extensible.">
  <nav class="flex items-center justify-between px-6 py-4 max-w-7xl mx-auto">
    <a href="/" class="text-xl font-bold text-stone-50">Nova</a>
    <div class="flex items-center gap-6">
      <a href="/docs/quickstart/" class="text-sm text-stone-400 hover:text-stone-200 transition-colors">Docs</a>
      <a href="/changelog/" class="text-sm text-stone-400 hover:text-stone-200 transition-colors">Changelog</a>
      <a href="https://github.com/arialabs/nova" target="_blank" rel="noopener noreferrer" class="text-sm text-stone-400 hover:text-stone-200 transition-colors">GitHub</a>
    </div>
  </nav>

  <Hero />

  <!-- Differentiators -->
  <section class="px-6 py-16 max-w-7xl mx-auto">
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {differentiators.map((d) => (
        <FeatureCard title={d.title} description={d.description} />
      ))}
    </div>
  </section>

  <!-- Features -->
  <section class="px-6 py-16 max-w-7xl mx-auto">
    <h2 class="text-2xl font-bold text-stone-100 mb-8 text-center">Everything You Need</h2>
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {features.map((f) => (
        <FeatureCard title={f.title} description={f.description} />
      ))}
    </div>
  </section>
</Landing>
```

**Step 4: Verify render**

```bash
cd /home/jeremy/workspace/nova/website
npx astro dev --port 4000
```

Visit `http://localhost:4000/`. Expected: Hero + 4 differentiator cards + 10 feature cards in grid.

**Step 5: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/src/data/features.ts website/src/components/FeatureCard.astro website/src/pages/index.astro
git commit -m "Add differentiators and features sections to landing page"
```

---

### Task 4: Pipeline Diagram & Install Section

**Files:**
- Create: `website/src/components/PipelineDiagram.astro`
- Create: `website/src/components/InstallBlock.astro`
- Create: `website/src/components/Footer.astro`
- Modify: `website/src/pages/index.astro`

**Step 1: Create PipelineDiagram component**

Create `website/src/components/PipelineDiagram.astro`:

```astro
---
const stages = [
  { name: 'Context Agent', description: 'Curates relevant code, docs, and task history', color: 'text-teal-400' },
  { name: 'Task Agent', description: 'Produces the actual output — code, config, or answer', color: 'text-emerald-400' },
  { name: 'Guardrail Agent', description: 'Checks for prompt injection, PII, credential leaks, spec drift', color: 'text-amber-400' },
  { name: 'Code Review', description: 'Pass, needs refactor, or reject — loops back up to 3 times', color: 'text-teal-400' },
  { name: 'Decision Agent', description: 'Creates decision record and escalates to human on rejection', color: 'text-rose-400' },
];

const postPipeline = ['Documentation', 'Diagramming', 'Security Review', 'Memory Extraction'];
---

<section class="px-6 py-16 max-w-4xl mx-auto">
  <h2 class="text-2xl font-bold text-stone-100 mb-2 text-center">The Pipeline</h2>
  <p class="text-sm text-stone-400 text-center mb-10">Every task runs through five specialized agents with built-in safety rails.</p>

  <div class="space-y-1">
    {stages.map((stage, i) => (
      <div class="flex items-start gap-4 py-3">
        <div class="flex flex-col items-center">
          <div class={`w-3 h-3 rounded-full border-2 ${stage.color} border-current`}></div>
          {i < stages.length - 1 && <div class="w-px h-8 bg-stone-700 mt-1"></div>}
        </div>
        <div>
          <span class={`text-sm font-semibold ${stage.color}`}>{stage.name}</span>
          <p class="text-sm text-stone-400 mt-0.5">{stage.description}</p>
        </div>
      </div>
    ))}
  </div>

  <div class="mt-8 rounded-lg border border-stone-800 bg-stone-900/30 p-4">
    <p class="text-xs font-medium text-stone-500 uppercase tracking-wide mb-2">Post-Pipeline (parallel, non-blocking)</p>
    <div class="flex flex-wrap gap-2">
      {postPipeline.map((agent) => (
        <span class="text-xs rounded-full border border-stone-700 px-3 py-1 text-stone-400">{agent}</span>
      ))}
    </div>
  </div>
</section>
```

**Step 2: Create InstallBlock component**

Create `website/src/components/InstallBlock.astro`:

```astro
<section id="install" class="px-6 py-16 max-w-3xl mx-auto">
  <h2 class="text-2xl font-bold text-stone-100 mb-2 text-center">Get Running in 3 Commands</h2>
  <p class="text-sm text-stone-400 text-center mb-8">The setup wizard detects your hardware, configures providers, and starts everything.</p>

  <div class="rounded-xl border border-stone-800 bg-stone-900 p-6 font-mono text-sm">
    <div class="space-y-1">
      <p><span class="text-stone-500">$</span> <span class="text-stone-200">git clone https://github.com/arialabs/nova.git</span></p>
      <p><span class="text-stone-500">$</span> <span class="text-stone-200">cd nova</span></p>
      <p><span class="text-stone-500">$</span> <span class="text-stone-200">./setup</span></p>
    </div>
  </div>

  <div class="mt-6 rounded-lg border border-stone-800 bg-stone-900/30 p-4">
    <p class="text-sm text-stone-300 font-medium">Remote GPU?</p>
    <p class="text-sm text-stone-400 mt-1">
      If you have a separate machine with a GPU, run the remote setup script on it, then re-run <code class="text-teal-400 bg-stone-800 px-1 py-0.5 rounded text-xs">./setup</code> and choose "Remote GPU".
    </p>
    <a href="/docs/deployment/" class="text-sm text-teal-400 hover:text-teal-300 mt-2 inline-block transition-colors">
      Deployment guide &rarr;
    </a>
  </div>
</section>
```

**Step 3: Create Footer component**

Create `website/src/components/Footer.astro`:

```astro
<footer class="border-t border-stone-800 px-6 py-8 mt-16">
  <div class="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
    <p class="text-sm text-stone-500">
      Built by <a href="https://arialabs.ai" class="text-stone-400 hover:text-stone-200 transition-colors">Aria Labs</a>
    </p>
    <div class="flex items-center gap-6">
      <a href="/docs/quickstart/" class="text-sm text-stone-500 hover:text-stone-300 transition-colors">Docs</a>
      <a href="https://github.com/arialabs/nova" target="_blank" rel="noopener noreferrer" class="text-sm text-stone-500 hover:text-stone-300 transition-colors">GitHub</a>
      <a href="/changelog/" class="text-sm text-stone-500 hover:text-stone-300 transition-colors">Changelog</a>
    </div>
  </div>
</footer>
```

**Step 4: Wire into landing page**

Modify `website/src/pages/index.astro` — add imports for PipelineDiagram, InstallBlock, Footer and place them after the Features section:

Add to imports:

```astro
import PipelineDiagram from '../components/PipelineDiagram.astro';
import InstallBlock from '../components/InstallBlock.astro';
import Footer from '../components/Footer.astro';
```

Add after the Features section `</section>`, before `</Landing>`:

```astro
  <PipelineDiagram />
  <InstallBlock />
  <Footer />
```

**Step 5: Verify full landing page**

```bash
cd /home/jeremy/workspace/nova/website
npx astro dev --port 4000
```

Expected: Full landing page — nav, hero, differentiators, features, pipeline diagram, install block, footer.

**Step 6: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/src/components/PipelineDiagram.astro website/src/components/InstallBlock.astro website/src/components/Footer.astro website/src/pages/index.astro
git commit -m "Add pipeline diagram, install block, and footer to landing page"
```

---

### Task 5: Core Documentation Pages

**Files:**
- Create: `website/src/content/docs/quickstart.md`
- Create: `website/src/content/docs/architecture.md`
- Create: `website/src/content/docs/pipeline.md`
- Create: `website/src/content/docs/configuration.md`

**Reference files to pull content from:**
- `README.md` — quick start, architecture table
- `CLAUDE.md` — architecture details, inter-service communication, build commands
- `docs/roadmap.md:127-206` — pipeline details (Phase 4)
- `.env.example` — configuration reference

**Step 1: Create quickstart.md**

Create `website/src/content/docs/quickstart.md`:

```markdown
---
title: Quick Start
description: Get Nova running in under 5 minutes.
---

## Prerequisites

- [Docker Desktop](https://docker.com/products/docker-desktop) (includes Docker Compose)

## Install

```bash
git clone https://github.com/arialabs/nova.git
cd nova
./setup
```

The setup wizard:
1. Copies `.env.example` to `.env` and prompts for API keys
2. Detects GPU hardware and recommends inference backends
3. Pulls required Docker images
4. Starts all services

Open **http://localhost:3001** when it's done.

## Remote GPU (optional)

If you have a separate machine with a GPU for local AI inference:

```bash
# Run this ON the GPU machine:
bash <(curl -s https://raw.githubusercontent.com/arialabs/nova/main/scripts/setup-remote-ollama.sh)
```

Then re-run `./setup` on the Nova machine and choose "Remote GPU".

## Manual Configuration

Copy `.env.example` to `.env`, edit it, and run:

```bash
make dev
```

See the [Configuration](/docs/configuration/) page for all options.

## Verify

Check that services are running:

```bash
make ps
```

Each service exposes health endpoints at `/health/live` and `/health/ready`.
```

**Step 2: Create architecture.md**

Create `website/src/content/docs/architecture.md`:

```markdown
---
title: Architecture
description: Nova's 8-service Docker Compose stack.
---

Nova runs as an 8-service Docker Compose stack. All inter-service communication is HTTP.

## Services

| Service | Port | Role |
|---------|------|------|
| **Orchestrator** | 8000 | Agent lifecycle, task queue, pipeline execution, MCP tool dispatch, DB migrations |
| **LLM Gateway** | 8001 | Multi-provider model routing via LiteLLM |
| **Memory Service** | 8002 | Embedding + hybrid semantic/keyword retrieval via pgvector |
| **Chat API** | 8080 | WebSocket streaming bridge for external clients |
| **Dashboard** | 3000 (prod) / 5173 (dev) | React admin UI |
| **PostgreSQL** | 5432 | pgvector-enabled PostgreSQL 16 |
| **Redis** | 6379 | State, task queue (BRPOP), rate limiting, session memory |
| **Recovery** | 8888 | Backup/restore, factory reset, service management |

## Communication Flow

- **Orchestrator** calls LLM Gateway (`/complete`, `/stream`, `/embed`) and Memory Service (`/api/v1/memories/*`)
- **Dashboard** proxies to Orchestrator (`/api`), LLM Gateway (`/v1`), and Recovery (`/recovery-api`)
- **Chat API** forwards to Orchestrator's streaming endpoint
- **Recovery** depends only on PostgreSQL — stays alive when other services crash

## Tech Stack

- **Backend:** Python + FastAPI + asyncpg + asyncio
- **Frontend:** Vite + React + TypeScript + Tailwind + TanStack Query
- **Database:** PostgreSQL 16 + pgvector
- **Queue:** Redis (BRPOP task dispatch with heartbeat and stale reaper)
- **Containers:** Docker Compose with hot reload

## Database

- Orchestrator uses raw asyncpg queries (no ORM)
- Memory Service uses SQLAlchemy async
- Migrations run automatically at orchestrator startup from versioned SQL files
- UUID primary keys, TIMESTAMPTZ, JSONB for flexible fields

## Redis DB Allocation

| Service | Redis DB |
|---------|----------|
| Memory Service | db0 |
| LLM Gateway | db1 |
| Orchestrator | db2 |
| Chat API | db3 |
```

**Step 3: Create pipeline.md**

Create `website/src/content/docs/pipeline.md` — pull from `docs/roadmap.md:127-206`:

```markdown
---
title: Agent Pipeline
description: Nova's 5-stage agent pipeline with safety rails.
---

Every task in Nova runs through a multi-agent pipeline with built-in safety checks. The pipeline executes via a Redis BRPOP task queue with heartbeat monitoring and stale task reaping.

## Pipeline Stages

```
Context Agent  -->  Task Agent  -->  Guardrail Agent  -->  Code Review  -->  Decision Agent
```

### 1. Context Agent

Curates relevant code, documentation, and prior task history. Provides the Task Agent with everything it needs to produce accurate output.

### 2. Task Agent

Produces the actual output — code, configuration, documentation, or answers. This is where the real work happens.

### 3. Guardrail Agent

Post-generation safety review. Checks for:
- Prompt injection attempts
- PII exposure
- Credential leaks
- Specification drift

Runs on a fast, cost-effective model (Haiku-class).

### 4. Code Review Agent

Reviews the Task Agent's output:
- **Pass** — output is good, proceed
- **Needs refactor** — loops back to Task Agent (max 3 iterations)
- **Reject** — escalates to Decision Agent

### 5. Decision Agent

Triggered only on rejection. Creates an Architecture Decision Record (ADR) artifact and escalates to human review.

## Post-Pipeline Agents

After the main pipeline completes, these agents run in parallel (best-effort, non-blocking):
- **Documentation Agent** — generates docs for the output
- **Diagramming Agent** — creates visual diagrams
- **Security Review Agent** — deeper security analysis
- **Memory Extraction Agent** — extracts learnings for future tasks

## Task Queue

- **Dispatch:** Redis BRPOP — long tasks don't block the HTTP layer
- **Heartbeat:** 30-second intervals
- **Stale reaper:** 150-second timeout for stuck tasks
- **Checkpoint:** After each stage, output is persisted to resume on retry
- **Dedup:** Redis SET gate prevents duplicate task enqueuing

## Pods

Pods are configurable pipeline presets. Each pod defines which agents run, in what order, with what models:

| Pod | Agents | Use Case |
|-----|--------|----------|
| **Quartet** (default) | Context, Task, Guardrail, Code Review | All code/config tasks |
| **Quick Reply** | Task only | Fast answers, low-stakes queries |
| **Research** | Context, Task (web search tools) | Information gathering |
| **Code Generation** | Full pipeline + git tools | Production code, auto-commit |
| **Analysis** | Context, Task (read-only tools) | Codebase audit, no writes |

All pod and agent settings are stored in the database and editable via the dashboard UI.
```

**Step 4: Create configuration.md**

Create `website/src/content/docs/configuration.md`:

```markdown
---
title: Configuration
description: Environment variables, models, and context budgets.
---

## Environment Variables

Nova is configured via a `.env` file in the project root. Run `./setup` to generate one from `.env.example`.

### Key Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | Database password | Set during setup |
| `ADMIN_SECRET` | Admin authentication secret | Set during setup |
| `DEFAULT_CHAT_MODEL` | Model used for interactive chat | `claude-sonnet-4-6` |
| `NOVA_WORKSPACE` | Host directory mounted at `/workspace` | `./workspace` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `REQUIRE_AUTH` | Enable API key authentication | `false` |

### Provider API Keys

Add keys for any providers you want to use:

| Variable | Provider |
|----------|----------|
| `ANTHROPIC_API_KEY` | Anthropic (Claude) |
| `OPENAI_API_KEY` | OpenAI (GPT) |
| `GROQ_API_KEY` | Groq |
| `GEMINI_API_KEY` | Google Gemini |
| `CEREBRAS_API_KEY` | Cerebras |
| `OPENROUTER_API_KEY` | OpenRouter |
| `GITHUB_TOKEN` | GitHub Models |

## models.yaml

Defines which Ollama models to auto-pull on startup. Edit via the dashboard Settings page or directly:

```yaml
models:
  - llama3.1:8b
  - codellama:13b
  - nomic-embed-text
```

## Context Budgets

Controls how the context window is allocated across components:

| Component | Budget |
|-----------|--------|
| System prompt | 10% |
| Tools | 15% |
| Memory | 40% |
| History | 20% |
| Working memory | 15% |

Editable in the dashboard Settings page under "Context Budgets".

## LLM Routing Strategy

Runtime-configurable routing strategies:
- **local-only** — only use local inference backends
- **local-first** — prefer local, fall back to cloud
- **cloud-only** — only use cloud providers
- **cloud-first** — prefer cloud, fall back to local

Set via the dashboard Settings page or the `LLM_ROUTING_STRATEGY` environment variable.
```

**Step 5: Verify docs render in Starlight**

```bash
cd /home/jeremy/workspace/nova/website
npx astro dev --port 4000
```

Visit `http://localhost:4000/docs/quickstart/`. Expected: Starlight-themed docs page with sidebar navigation showing all four pages under "Core Concepts".

**Step 6: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/src/content/docs/quickstart.md website/src/content/docs/architecture.md website/src/content/docs/pipeline.md website/src/content/docs/configuration.md
git commit -m "Add core documentation: quickstart, architecture, pipeline, configuration"
```

---

### Task 6: Inference Backends & Deployment Docs

**Files:**
- Create: `website/src/content/docs/inference-backends.md`
- Create: `website/src/content/docs/deployment.md`

**Reference:** `docs/roadmap.md:2039-2194` (Phase 12)

**Step 1: Create inference-backends.md**

Create `website/src/content/docs/inference-backends.md`:

```markdown
---
title: Inference Backends
description: Choose the right local inference engine for your workload.
---

Nova supports four local inference backends. Each exposes an OpenAI-compatible API, and LLM Gateway abstracts the provider layer — adding a backend is configuration, not code.

## Comparison

| Capability | Ollama | vLLM | llama.cpp | SGLang |
|-----------|--------|------|-----------|--------|
| **Concurrent batching** | Sequential queue | Continuous batching | Limited parallel slots | Continuous batching + RadixAttention |
| **Multi-user serving** | Latency degrades linearly | Near-constant up to batch capacity | Better than Ollama | Best for shared-prefix workloads |
| **VRAM efficiency** | Loads/unloads full models | PagedAttention | Manual KV cache sizing | RadixAttention prefix caching |
| **Model switching** | Hot-swap via `ollama pull` | Single model per instance | Single model per instance | Single model per instance |
| **Quantization** | GGUF (widest variety) | GPTQ, AWQ, FP8, GGUF | GGUF native (fastest) | GPTQ, AWQ, FP8, GGUF |
| **CPU inference** | Yes (good) | GPU only | Yes (excellent) | GPU only |
| **Setup complexity** | Single binary, trivial | Python env, more config | Single binary, moderate | Python env, similar to vLLM |
| **Docker image** | `ollama/ollama` | `vllm/vllm-openai` | `ghcr.io/ggerganov/llama.cpp:server` | `lmsysorg/sglang` |

## Why SGLang for Nova

SGLang's **RadixAttention** automatically caches shared prefixes across requests. Nova's pipeline agents (Context, Task, Guardrail, Code Review) share system prompts that are identical across task executions. With 5 parallel tasks, that's 20 agent calls sharing large system prompt prefixes — SGLang caches these in a radix tree, skipping redundant computation.

## Recommended Strategy

| Workload | Backend | Why |
|----------|---------|-----|
| Single user, model experimentation | Ollama | Hot-swap models, widest GGUF library |
| Multi-tenant chat | vLLM or SGLang | Continuous batching handles concurrent users |
| Parallel agent pipelines | SGLang | RadixAttention prefix caching |
| CPU-only / edge | llama.cpp | Best CPU performance, smallest footprint |
| Hybrid (recommended default) | Ollama + SGLang | Ollama for variety, SGLang for serving |

## Enabling Backends

Each backend is a Docker Compose profile. Enable via `.env`:

```bash
COMPOSE_PROFILES=local-ollama,local-sglang
```

Or start individually:

```bash
docker compose --profile local-vllm up -d
```

The setup wizard (`./setup`) auto-detects your GPU and recommends backends.

## Configuration

Backend-specific environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_MODEL` | `meta-llama/Llama-3.1-70B-Instruct-AWQ` | Model for vLLM |
| `VLLM_MAX_MODEL_LEN` | `4096` | Max context length |
| `SGLANG_MODEL` | `meta-llama/Llama-3.1-70B-Instruct-AWQ` | Model for SGLang |
| `LLAMACPP_MODEL` | `model.gguf` | GGUF model file for llama.cpp |
| `LLAMACPP_CTX_SIZE` | `4096` | Context size for llama.cpp |
| `LLAMACPP_PARALLEL` | `4` | Parallel request slots |
```

**Step 2: Create deployment.md**

Create `website/src/content/docs/deployment.md`:

```markdown
---
title: Deployment
description: Docker Compose, GPU overlays, and remote inference.
---

## Quick Start

```bash
git clone https://github.com/arialabs/nova.git
cd nova
./setup
```

## Development

```bash
make dev          # Docker Compose with hot reload
make watch        # Sync Python source into running containers
make logs         # Tail all container logs
make ps           # Container status
```

## Production

```bash
make build        # Rebuild all images
make up           # Start detached
make down         # Stop all
```

## GPU Overlays

GPU support is auto-detected by `./setup`. To enable manually:

```bash
# NVIDIA
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

# AMD ROCm
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d
```

## Remote GPU

Nova supports running inference on a separate GPU machine over LAN:

1. Run the setup script on the GPU machine:
   ```bash
   bash <(curl -s https://raw.githubusercontent.com/arialabs/nova/main/scripts/setup-remote-ollama.sh)
   ```
2. Re-run `./setup` on the Nova machine and choose "Remote GPU"
3. Nova uses Wake-on-LAN to wake the GPU machine when needed

## Inference Backend Selection

See [Inference Backends](/docs/inference-backends/) for a comparison of Ollama, vLLM, llama.cpp, and SGLang.

Enable backends via Docker Compose profiles in `.env`:

```bash
COMPOSE_PROFILES=local-ollama,local-sglang
```

## Backup & Restore

```bash
make backup               # Create database backup to ./backups/
make restore               # List available backups
make restore F=<file>     # Restore a specific backup
```

The Recovery service at port 8888 provides a web UI for backup/restore, factory reset, and service management. Access it via the dashboard at `/recovery`.
```

**Step 3: Verify**

```bash
cd /home/jeremy/workspace/nova/website
npx astro build
```

Expected: Build succeeds, no errors.

**Step 4: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/src/content/docs/inference-backends.md website/src/content/docs/deployment.md
git commit -m "Add inference backends and deployment docs"
```

---

### Task 7: Remaining Docs Pages (Services, Guides, Reference)

**Files:**
- Create: `website/src/content/docs/services/orchestrator.md`
- Create: `website/src/content/docs/services/llm-gateway.md`
- Create: `website/src/content/docs/services/memory-service.md`
- Create: `website/src/content/docs/services/chat-api.md`
- Create: `website/src/content/docs/services/dashboard.md`
- Create: `website/src/content/docs/services/recovery.md`
- Create: `website/src/content/docs/remote-access.md`
- Create: `website/src/content/docs/ide-integration.md`
- Create: `website/src/content/docs/mcp-tools.md`
- Create: `website/src/content/docs/security.md`
- Create: `website/src/content/docs/skills-rules.md`
- Create: `website/src/content/docs/api-reference.md`
- Create: `website/src/content/docs/roadmap.md`

**Reference files:**
- `docs/ide-integration.md` — copy and adapt for IDE integration page
- `docs/roadmap.md` — roadmap content
- `CLAUDE.md` — service details, API design, auth patterns
- `dashboard/src/pages/RemoteAccess.tsx` — remote access details
- `dashboard/src/lib/mcp-catalog.ts` — MCP server catalog
- `orchestrator/app/pipeline/agents/` — pipeline agent details

**Implementation note:** Each of these is a Starlight markdown file with frontmatter (`title`, `description`). Content should be pulled from the reference files listed above, adapted for external documentation tone.

**Step 1: Create all service docs**

Each service doc should follow this template:

```markdown
---
title: [Service Name]
description: [One-line description]
---

## Overview

[2-3 sentences about what this service does]

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/live` | Liveness check |
| GET | `/health/ready` | Readiness check |
| ... | ... | ... |

## Configuration

[Relevant env vars]

## Implementation Notes

[Key technical details]
```

Create each file with accurate content from the codebase. For the orchestrator, include pipeline, task queue, and MCP details. For LLM Gateway, include provider routing and model registry. For Memory Service, include embedding and retrieval. Etc.

**Step 2: Create ide-integration.md**

Adapt from `docs/ide-integration.md` — this content is already well-written. Copy it into `website/src/content/docs/ide-integration.md` with Starlight frontmatter:

```markdown
---
title: IDE Integration
description: Use Nova as an OpenAI-compatible backend in your IDE.
---
```

Then paste the existing content from `docs/ide-integration.md` below the frontmatter.

**Step 3: Create remaining guide and reference pages**

Each page follows the same pattern: frontmatter + content adapted from codebase sources.

For `mcp-tools.md` — pull from `dashboard/src/lib/mcp-catalog.ts` to list available MCP servers.

For `security.md` — cover API key auth, admin secret, sandbox tiers, data privacy.

For `skills-rules.md` — pull from `docs/roadmap.md:243-430` (Phase 5c).

For `api-reference.md` — document REST endpoints per service.

For `roadmap.md` — adapt the existing `docs/roadmap.md` or link to the GitHub source.

For `remote-access.md` — document Cloudflare Tunnel and Tailscale setup from the dashboard.

**Step 4: Verify sidebar renders all pages**

```bash
cd /home/jeremy/workspace/nova/website
npx astro dev --port 4000
```

Expected: Sidebar shows all sections from `astro.config.mjs` with every page navigable.

**Step 5: Build check**

```bash
cd /home/jeremy/workspace/nova/website
npx astro build
```

Expected: Clean build, no broken links.

**Step 6: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/src/content/docs/
git commit -m "Add service docs, guides, and reference pages"
```

---

### Task 8: Changelog System

**Files:**
- Create: `website/src/pages/changelog.astro`
- Create: `website/src/content/changelog/2026-03-06.md` (initial entry)
- Modify: `website/src/content.config.ts` (ensure changelog collection is defined)

**Step 1: Create initial changelog entry**

Create `website/src/content/changelog/2026-03-06.md`:

```markdown
---
title: "Remote Access & Navigation"
date: 2026-03-06
---

## Dashboard: Remote Access & Navigation

- Added Remote Access page with Cloudflare Tunnel and Tailscale setup wizards
- Updated NavBar with improved navigation structure
- Expanded MCP server catalog with new entries
- Shared UI primitives and mobile responsiveness improvements
```

**Step 2: Backfill a few more changelog entries from git history**

Create `website/src/content/changelog/2026-03-05.md`:

```markdown
---
title: "UI Primitives & Mobile"
date: 2026-03-05
---

## Dashboard: Shared UI & Mobile

- Introduced shared UI primitives for consistent component design
- Fixed mobile layout overflow across all dashboard pages
- CSS deduplication pass
```

Create `website/src/content/changelog/2026-02-recovery.md`:

```markdown
---
title: "Recovery Service"
date: 2026-02-15
---

## Recovery Service

- Added recovery sidecar service for backup/restore and factory reset
- Database backup/restore via CLI and web UI
- Service management with Docker SDK integration
- Startup screen showing services coming online
```

**Step 3: Create changelog listing page**

Create `website/src/pages/changelog.astro`:

```astro
---
import Landing from '../layouts/Landing.astro';
import Footer from '../components/Footer.astro';
import { getCollection } from 'astro:content';

const entries = (await getCollection('changelog'))
  .sort((a, b) => new Date(b.data.date).getTime() - new Date(a.data.date).getTime());
---

<Landing title="Changelog — Nova" description="What's new in Nova.">
  <nav class="flex items-center justify-between px-6 py-4 max-w-7xl mx-auto">
    <a href="/" class="text-xl font-bold text-stone-50">Nova</a>
    <div class="flex items-center gap-6">
      <a href="/docs/quickstart/" class="text-sm text-stone-400 hover:text-stone-200 transition-colors">Docs</a>
      <a href="/changelog/" class="text-sm text-teal-400 transition-colors">Changelog</a>
      <a href="https://github.com/arialabs/nova" target="_blank" rel="noopener noreferrer" class="text-sm text-stone-400 hover:text-stone-200 transition-colors">GitHub</a>
    </div>
  </nav>

  <main class="px-6 py-16 max-w-3xl mx-auto">
    <h1 class="text-3xl font-bold text-stone-100 mb-8">Changelog</h1>

    <div class="space-y-12">
      {entries.map(async (entry) => {
        const { Content } = await entry.render();
        return (
          <article class="border-l-2 border-stone-800 pl-6">
            <time class="text-xs font-medium text-stone-500 uppercase tracking-wide">
              {new Date(entry.data.date).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
            </time>
            <div class="mt-2 prose prose-invert prose-sm prose-stone max-w-none">
              <Content />
            </div>
          </article>
        );
      })}
    </div>
  </main>

  <Footer />
</Landing>
```

**Step 4: Verify changelog renders**

```bash
cd /home/jeremy/workspace/nova/website
npx astro dev --port 4000
```

Visit `http://localhost:4000/changelog/`. Expected: Changelog page with entries sorted newest first, left border accent, date headers.

**Step 5: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/src/pages/changelog.astro website/src/content/changelog/ website/src/content.config.ts
git commit -m "Add changelog system with initial entries"
```

---

### Task 9: Final Polish & Build Verification

**Files:**
- Create: `website/public/favicon.svg`
- Modify: `website/src/pages/index.astro` (final review)
- Modify: `website/astro.config.mjs` (verify sidebar matches actual pages)

**Step 1: Create favicon**

Create `website/public/favicon.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="#0d9488"/>
  <text x="50%" y="50%" dominant-baseline="central" text-anchor="middle" font-family="system-ui" font-size="18" font-weight="700" fill="white">N</text>
</svg>
```

**Step 2: Full build check**

```bash
cd /home/jeremy/workspace/nova/website
npx astro build
```

Expected: Clean build, no warnings about missing pages or broken links.

**Step 3: Preview production build**

```bash
cd /home/jeremy/workspace/nova/website
npx astro preview --port 4000
```

Visit `http://localhost:4000/` and click through:
- Landing page: all sections render
- Nav links work (Docs, Changelog, GitHub)
- `/docs/quickstart/` loads with sidebar
- Sidebar navigation works for all pages
- `/changelog/` shows entries
- Dark mode colors are correct (teal accents, stone backgrounds)
- Mobile responsive (resize browser)

**Step 4: Commit**

```bash
cd /home/jeremy/workspace/nova
git add website/public/ website/src/
git commit -m "Final polish: favicon, build verification"
```

---

### Task 10: Cloudflare Pages Deployment

**Files:**
- No new files — this is infrastructure configuration

**Step 1: Connect repo to Cloudflare Pages**

Option A — via Cloudflare dashboard:
1. Go to Cloudflare dashboard > Workers & Pages > Create
2. Connect GitHub repo `arialabs/nova`
3. Set build settings:
   - **Build command:** `cd website && npm install && npm run build`
   - **Build output directory:** `website/dist`
   - **Root directory:** `/` (monorepo root)
4. Set custom domain to `nova.arialabs.ai`

Option B — via Wrangler CLI:

```bash
cd /home/jeremy/workspace/nova/website
npx wrangler pages project create nova-website
npx wrangler pages deploy dist --project-name nova-website
```

Then configure custom domain in Cloudflare dashboard.

**Step 2: Add build script to website package.json**

Ensure `website/package.json` has:

```json
{
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview"
  }
}
```

**Step 3: Verify deployment**

After first deploy, visit `https://nova.arialabs.ai` and verify the site loads correctly.

**Step 4: Commit any deployment config changes**

```bash
cd /home/jeremy/workspace/nova
git add website/
git commit -m "Configure website for Cloudflare Pages deployment"
```
