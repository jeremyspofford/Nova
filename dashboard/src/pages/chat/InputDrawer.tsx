import { Paperclip } from 'lucide-react'
import { VoiceButton } from './VoiceButton'
import { OutputStylePicker } from './OutputStylePicker'
import { ResearchToggles } from './ResearchToggles'
import { Tooltip } from '../../components/ui/Tooltip'

interface Props {
  open: boolean
  onAttach: () => void
  onTranscript: (text: string) => void
  onLiveState?: (state: { isListening: boolean; transcript: string }) => void
}

export function InputDrawer({ open, onAttach, onTranscript, onLiveState }: Props) {
  return (
    <div
      className="overflow-hidden transition-all duration-normal ease-out"
      style={{ maxHeight: open ? '300px' : '0px', opacity: open ? 1 : 0 }}
    >
      <div className="flex flex-col sm:flex-row gap-3 pb-2 pt-2 border-t border-border-subtle mb-2">
        {/* Left: action buttons */}
        <div className="flex sm:flex-col gap-1">
          <Tooltip content="Attach file">
            <button
              type="button"
              onClick={onAttach}
              className="flex items-center justify-center rounded-sm p-2 text-content-tertiary hover:bg-surface-elevated hover:text-content-primary transition-colors duration-fast"
            >
              <Paperclip size={16} />
            </button>
          </Tooltip>
          <VoiceButton onTranscript={onTranscript} onLiveState={onLiveState} />
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
