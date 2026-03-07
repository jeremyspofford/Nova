import { Paperclip } from 'lucide-react'
import { VoiceButton } from './VoiceButton'
import { OutputStylePicker } from './OutputStylePicker'
import { ResearchToggles } from './ResearchToggles'

interface Props {
  open: boolean
  onAttach: () => void
  onTranscript: (text: string) => void
}

export function InputDrawer({ open, onAttach, onTranscript }: Props) {
  return (
    <div
      className="overflow-hidden transition-all duration-200 ease-out"
      style={{ maxHeight: open ? '300px' : '0px', opacity: open ? 1 : 0 }}
    >
      <div className="flex flex-col sm:flex-row gap-3 pb-2 pt-2 border-t border-neutral-100 dark:border-neutral-800 mb-2">
        {/* Left: action buttons */}
        <div className="flex sm:flex-col gap-1">
          <button
            type="button"
            onClick={onAttach}
            title="Attach file"
            className="flex items-center justify-center rounded-lg p-2 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
          >
            <Paperclip size={16} />
          </button>
          <VoiceButton onTranscript={onTranscript} />
        </div>

        {/* Right: style + research */}
        <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <OutputStylePicker />
          <ResearchToggles />
        </div>
      </div>
    </div>
  )
}
