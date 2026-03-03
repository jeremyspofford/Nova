export interface CatalogEnvVar {
  key: string
  label: string
  description: string
  placeholder: string
  required: boolean
  default?: string
}

export interface CatalogEntry {
  id: string
  name: string
  displayName: string
  description: string
  command: string
  args: string[]
  env: CatalogEnvVar[]
  tags: string[]
  docs?: string
  note?: string
}

export const MCP_CATALOG: CatalogEntry[] = [
  {
    id: 'filesystem',
    name: 'filesystem',
    displayName: 'Filesystem',
    description: 'Read, write, and navigate files. Requires a path argument for the workspace root.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-filesystem', '/workspace'],
    env: [],
    tags: ['core', 'files'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem',
    note: 'The last argument is the allowed root path. Change /workspace to match your container or local path.',
  },
  {
    id: 'git',
    name: 'git',
    displayName: 'Git',
    description: 'Inspect and operate on Git repositories — log, diff, status, commit, and more.',
    command: 'uvx',
    args: ['mcp-server-git', '--repository', '/workspace'],
    env: [],
    tags: ['core', 'git', 'dev'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/git',
    note: 'Change /workspace to the path of the repository you want to expose.',
  },
  {
    id: 'brave-search',
    name: 'brave-search',
    displayName: 'Brave Search',
    description: 'Web and local search powered by the Brave Search API.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-brave-search'],
    env: [
      {
        key: 'BRAVE_API_KEY',
        label: 'Brave API Key',
        description: 'Get a free key at https://brave.com/search/api/',
        placeholder: 'BSA...',
        required: true,
      },
    ],
    tags: ['search', 'web'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search',
  },
  {
    id: 'github',
    name: 'github',
    displayName: 'GitHub',
    description: 'Manage repos, issues, pull requests, and code search via the GitHub API.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-github'],
    env: [
      {
        key: 'GITHUB_PERSONAL_ACCESS_TOKEN',
        label: 'GitHub Personal Access Token',
        description: 'Create a token at https://github.com/settings/tokens — needs repo scope.',
        placeholder: 'ghp_...',
        required: true,
      },
    ],
    tags: ['dev', 'git'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/github',
  },
  {
    id: 'gitlab',
    name: 'gitlab',
    displayName: 'GitLab',
    description: 'Interact with GitLab projects, merge requests, and issues.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-gitlab'],
    env: [
      {
        key: 'GITLAB_PERSONAL_ACCESS_TOKEN',
        label: 'GitLab Personal Access Token',
        description: 'Create a token in GitLab → User Settings → Access Tokens.',
        placeholder: 'glpat-...',
        required: true,
      },
      {
        key: 'GITLAB_API_URL',
        label: 'GitLab API URL',
        description: 'Leave default for gitlab.com, or set your self-hosted instance URL.',
        placeholder: 'https://gitlab.com',
        required: false,
        default: 'https://gitlab.com',
      },
    ],
    tags: ['dev', 'git'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/gitlab',
  },
  {
    id: 'fetch',
    name: 'fetch',
    displayName: 'Fetch',
    description: 'Fetch arbitrary URLs and convert web pages to Markdown for AI consumption.',
    command: 'uvx',
    args: ['mcp-server-fetch'],
    env: [],
    tags: ['web'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/fetch',
  },
  {
    id: 'puppeteer',
    name: 'puppeteer',
    displayName: 'Puppeteer',
    description: 'Browser automation — screenshot, click, fill forms, and scrape dynamic pages.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-puppeteer'],
    env: [],
    tags: ['browser', 'web'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer',
  },
  {
    id: 'postgres',
    name: 'postgres',
    displayName: 'PostgreSQL',
    description: 'Query a PostgreSQL database. Connection URL goes as the last argument.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-postgres', 'postgresql://user:pass@localhost/db'],
    env: [],
    tags: ['database', 'sql'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/postgres',
    note: 'Replace the last argument with your actual PostgreSQL connection URL.',
  },
  {
    id: 'sqlite',
    name: 'sqlite',
    displayName: 'SQLite',
    description: 'Read and query a SQLite database file.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-sqlite', '/workspace/db.sqlite'],
    env: [],
    tags: ['database', 'sql'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite',
    note: 'Replace /workspace/db.sqlite with the actual path to your database file.',
  },
  {
    id: 'memory',
    name: 'memory',
    displayName: 'Memory',
    description: 'Persistent key-value memory store that survives across agent sessions.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-memory'],
    env: [],
    tags: ['ai', 'memory', 'core'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/memory',
  },
  {
    id: 'sequential-thinking',
    name: 'sequential-thinking',
    displayName: 'Sequential Thinking',
    description: 'Structured multi-step reasoning tool for complex problem decomposition.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-sequential-thinking'],
    env: [],
    tags: ['ai'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking',
  },
  {
    id: 'slack',
    name: 'slack',
    displayName: 'Slack',
    description: 'Read channels, send messages, and search Slack workspaces.',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-slack'],
    env: [
      {
        key: 'SLACK_BOT_TOKEN',
        label: 'Slack Bot Token',
        description: 'Create a Slack app at api.slack.com and copy the Bot User OAuth Token.',
        placeholder: 'xoxb-...',
        required: true,
      },
      {
        key: 'SLACK_TEAM_ID',
        label: 'Slack Team ID',
        description: 'Found in your Slack workspace URL: https://app.slack.com/client/TXXXXXXXX',
        placeholder: 'T...',
        required: true,
      },
    ],
    tags: ['communication'],
    docs: 'https://github.com/modelcontextprotocol/servers/tree/main/src/slack',
  },
]

export const ALL_TAGS = Array.from(
  new Set(MCP_CATALOG.flatMap(e => e.tags))
).sort()
