import { Mic, MicOff } from 'lucide-react'
import { useSpeechToText } from '../../hooks/useSpeechToText'
import { useEffect, useRef } from 'react'
import clsx from 'clsx'
import { Tooltip } from '../../components/ui/Tooltip'

interface Props {
  onTranscript: (text: string) => void
}

export function VoiceButton({ onTranscript }: Props) {
  const { isListening, transcript, start, stop, isSupported } = useSpeechToText()
  const prevTranscript = useRef('')

  useEffect(() => {
    if (transcript && transcript !== prevTranscript.current) {
      prevTranscript.current = transcript
    }
  }, [transcript])

  useEffect(() => {
    // When recording stops, emit the final transcript
    if (!isListening && prevTranscript.current) {
      onTranscript(prevTranscript.current)
      prevTranscript.current = ''
    }
  }, [isListening, onTranscript])

  if (!isSupported) return null

  return (
    <Tooltip content={isListening ? 'Stop recording' : 'Voice input'}>
      <button
        type="button"
        onClick={isListening ? stop : start}
        className={clsx(
          'flex items-center justify-center rounded-sm p-2 transition-colors duration-fast',
          isListening
            ? 'bg-danger-dim text-danger'
            : 'text-content-tertiary hover:bg-surface-elevated hover:text-content-primary',
        )}
      >
        {isListening ? (
          <MicOff size={16} className="animate-pulse" />
        ) : (
          <Mic size={16} />
        )}
      </button>
    </Tooltip>
  )
}
