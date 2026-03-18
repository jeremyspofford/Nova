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
      <label className="block text-caption font-medium text-content-secondary">
        Output Style
      </label>
      <select
        value={outputStyle}
        onChange={e => {
          setOutputStyle(e.target.value)
          localStorage.setItem('nova_output_style', e.target.value)
        }}
        className="h-8 w-full rounded-sm border border-border bg-surface-input px-2 text-caption text-content-primary outline-none transition-colors duration-fast focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 appearance-none bg-[length:14px_14px] bg-[position:right_6px_center] bg-no-repeat bg-[url('data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2216%22%20height%3D%2216%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%23999%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpath%20d%3D%22m6%209%206%206%206-6%22%2F%3E%3C%2Fsvg%3E')] pr-7"
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
        className="w-full resize-none rounded-sm border border-border bg-surface-input px-2 py-1.5 text-caption text-content-primary placeholder:text-content-tertiary outline-none transition-colors duration-fast focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
      />
    </div>
  )
}
