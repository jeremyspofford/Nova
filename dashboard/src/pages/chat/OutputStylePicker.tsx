import { useChatStore } from '../../stores/chat-store'

const PRESETS = [
  { value: '', label: 'Default' },
  { value: 'concise', label: 'Concise' },
  { value: 'detailed', label: 'Detailed' },
  { value: 'technical', label: 'Technical' },
  { value: 'creative', label: 'Creative' },
  { value: 'eli5', label: 'ELI5' },
]

export function OutputStylePicker() {
  const { outputStyle, setOutputStyle, customInstructions, setCustomInstructions } = useChatStore()

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-neutral-500 dark:text-neutral-400">
        Output Style
      </label>
      <select
        value={outputStyle}
        onChange={e => {
          setOutputStyle(e.target.value)
          localStorage.setItem('nova_output_style', e.target.value)
        }}
        className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-2 py-1.5 text-xs text-neutral-700 dark:text-neutral-300 outline-none focus:border-accent-600"
      >
        {PRESETS.map(p => (
          <option key={p.value} value={p.value}>{p.label}</option>
        ))}
      </select>
      <textarea
        value={customInstructions}
        onChange={e => {
          setCustomInstructions(e.target.value)
          localStorage.setItem('nova_custom_instructions', e.target.value)
        }}
        placeholder="Custom instructions..."
        rows={2}
        className="w-full resize-none rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-2 py-1.5 text-xs text-neutral-700 dark:text-neutral-300 placeholder:text-neutral-400 dark:placeholder:text-neutral-500 outline-none focus:border-accent-600"
      />
    </div>
  )
}
