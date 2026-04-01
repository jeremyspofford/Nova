// dashboard/src/pages/editors/editorConfigs.ts

export type EditorSlug = 'continue' | 'cline' | 'cursor' | 'aider' | 'windsurf' | 'generic'

export interface EditorMeta {
  slug: EditorSlug
  name: string
  description: string
  configFormat: 'json' | 'cli' | 'instructions' | 'curl'
}

export const EDITORS: EditorMeta[] = [
  { slug: 'continue', name: 'Continue.dev', description: 'VS Code & JetBrains', configFormat: 'json' },
  { slug: 'cline', name: 'Cline', description: 'VS Code — agentic coding', configFormat: 'json' },
  { slug: 'cursor', name: 'Cursor', description: 'AI-native editor', configFormat: 'instructions' },
  { slug: 'aider', name: 'Aider', description: 'Terminal', configFormat: 'cli' },
  { slug: 'windsurf', name: 'Windsurf', description: 'Codium editor', configFormat: 'json' },
  { slug: 'generic', name: 'Other / Generic', description: 'Any OpenAI-compatible tool', configFormat: 'curl' },
]

export const EDITOR_SLUGS = EDITORS.map(e => e.slug) as readonly EditorSlug[]

/**
 * Generate the config snippet a user pastes into their editor.
 */
export function generateConfig(
  slug: EditorSlug,
  endpoint: string,
  model: string,
  apiKey: string,
): string {
  switch (slug) {
    case 'continue':
      return JSON.stringify({
        title: `Nova (${model.split('/').pop()})`,
        provider: 'openai',
        model,
        apiBase: endpoint,
        apiKey,
      }, null, 2)

    case 'cline':
      return JSON.stringify({
        apiProvider: 'openai-compatible',
        openaiBaseUrl: endpoint,
        openaiModelId: model,
        openaiApiKey: apiKey,
      }, null, 2)

    case 'cursor':
      // Cursor uses a UI form, not a config file
      return [
        `Base URL:  ${endpoint}`,
        `API Key:   ${apiKey}`,
        `Model:     ${model}`,
      ].join('\n')

    case 'aider':
      return `aider \\
  --openai-api-base ${endpoint} \\
  --openai-api-key ${apiKey} \\
  --model ${model}`

    case 'windsurf':
      return JSON.stringify({
        title: `Nova (${model.split('/').pop()})`,
        provider: 'openai',
        model,
        apiBase: endpoint,
        apiKey,
      }, null, 2)

    case 'generic':
      return `curl ${endpoint}/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey}" \\
  -d '{
    "model": "${model}",
    "messages": [{"role": "user", "content": "Hello from Nova"}]
  }'`
  }
}

/**
 * Editor-specific paste instructions (step-by-step).
 */
export function getPasteInstructions(slug: EditorSlug): string[] {
  switch (slug) {
    case 'continue':
      return [
        'Open VS Code or JetBrains',
        'Cmd+Shift+P (or Ctrl+Shift+P) → "Continue: Open config.json"',
        'Add the JSON above to the "models" array',
        'Save the file — the model appears in the Continue sidebar',
      ]
    case 'cline':
      return [
        'Open VS Code',
        'Click the Cline icon in the sidebar',
        'Open Settings (gear icon)',
        'Select "OpenAI Compatible" as the API provider',
        'Paste the Base URL, API Key, and Model ID from the config above',
      ]
    case 'cursor':
      return [
        'Open Cursor → Settings → Models',
        'Click "Add model"',
        'Enter the Base URL, API Key, and Model name shown above',
        'Click Save',
      ]
    case 'aider':
      return [
        'Open a terminal in your project directory',
        'Run the command above (or add flags to your .aider.conf.yml)',
      ]
    case 'windsurf':
      return [
        'Open Windsurf → Settings',
        'Navigate to AI Provider configuration',
        'Add a new OpenAI-compatible provider',
        'Paste the JSON config above',
      ]
    case 'generic':
      return [
        'Use the endpoint URL and API key in any OpenAI-compatible tool',
        'The curl example above shows the exact request format',
      ]
  }
}
