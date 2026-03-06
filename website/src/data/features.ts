export interface Feature {
  title: string;
  description: string;
}

export const differentiators: Feature[] = [
  {
    title: 'Self-Directed',
    description: 'Define a goal. Nova breaks it into subtasks, executes autonomously, re-plans as needed.',
  },
  {
    title: 'Self-Improving',
    description: 'Learns your preferences, customizes itself, updates its own configuration over time.',
  },
  {
    title: 'Private & Secure',
    description: 'Runs entirely on your hardware. Your data never leaves. Sandbox tiers control what agents can access.',
  },
  {
    title: 'Parallel By Design',
    description: 'Continuous batching, concurrent pipelines, 4 inference backends. No bottleneck.',
  },
];

export const features: Feature[] = [
  {
    title: '4 Inference Backends',
    description: 'Ollama, vLLM, llama.cpp, SGLang. Pick the right engine for your workload. Run multiple simultaneously.',
  },
  {
    title: 'RadixAttention Optimization',
    description: 'SGLang caches shared agent system prompts across parallel tasks for significant inference speedup.',
  },
  {
    title: 'Skills & Rules',
    description: 'Extensible prompt templates and declarative behavior constraints without code changes.',
  },
  {
    title: 'Sandbox Tiers',
    description: 'Isolated, nova, workspace, host — execution environments with security-first defaults.',
  },
  {
    title: 'MCP Tool Ecosystem',
    description: 'Plug in any MCP server: GitHub, Slack, Sentry, Playwright, Docker, and more.',
  },
  {
    title: 'Multi-Provider LLM Routing',
    description: 'Anthropic, OpenAI, Ollama, Groq, Gemini, Cerebras, OpenRouter, plus subscription-based Claude/ChatGPT.',
  },
  {
    title: 'GPU-Aware Setup',
    description: 'Auto-detects hardware, recommends backends, supports remote GPU over LAN with Wake-on-LAN.',
  },
  {
    title: 'Recovery & Resilience',
    description: 'Backup/restore, factory reset, service health monitoring via dedicated sidecar service.',
  },
  {
    title: 'IDE Integration',
    description: 'OpenAI-compatible endpoint works with Cursor, Continue.dev, Aider, and any OpenAI-API client.',
  },
  {
    title: 'Self-Configuration',
    description: 'Nova can modify its own settings, prompts, and pod definitions via the nova sandbox tier.',
  },
];
