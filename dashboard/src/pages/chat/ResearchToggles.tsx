import { Globe, BookOpen } from 'lucide-react'
import { useChatStore } from '../../stores/chat-store'

export function ResearchToggles() {
  const {
    webSearchEnabled, setWebSearchEnabled,
    deepResearchEnabled, setDeepResearchEnabled,
  } = useChatStore()

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-neutral-500 dark:text-neutral-400">
        Research
      </label>
      <div className="space-y-1.5">
        <ToggleRow
          icon={<Globe size={14} />}
          label="Web Search"
          checked={webSearchEnabled}
          onChange={setWebSearchEnabled}
        />
        <ToggleRow
          icon={<BookOpen size={14} />}
          label="Deep Research"
          description={deepResearchEnabled ? 'Multi-step research with cross-referencing' : undefined}
          checked={deepResearchEnabled}
          onChange={setDeepResearchEnabled}
        />
      </div>
    </div>
  )
}

function ToggleRow({ icon, label, description, checked, onChange }: {
  icon: React.ReactNode
  label: string
  description?: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div>
      <label className="flex items-center gap-2 cursor-pointer group">
        <span className="text-neutral-500 dark:text-neutral-400 group-hover:text-neutral-700 dark:group-hover:text-neutral-300 transition-colors">
          {icon}
        </span>
        <span className="flex-1 text-xs text-neutral-700 dark:text-neutral-300">{label}</span>
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          onClick={() => onChange(!checked)}
          className={`relative h-5 w-9 rounded-full transition-colors ${
            checked ? 'bg-accent-700' : 'bg-neutral-300 dark:bg-neutral-600'
          }`}
        >
          <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-4' : 'translate-x-0'
          }`} />
        </button>
      </label>
      {description && (
        <p className="ml-6 mt-0.5 text-[10px] text-neutral-400 dark:text-neutral-500">{description}</p>
      )}
    </div>
  )
}
