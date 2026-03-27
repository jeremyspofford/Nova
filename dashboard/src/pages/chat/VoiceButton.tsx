import { Mic, MicOff } from 'lucide-react'
import { useSpeechToText } from '../../hooks/useSpeechToText'
import { useAudioLevel } from '../../hooks/useAudioLevel'
import { AudioLevelIndicator } from '../../components/ui/AudioLevelIndicator'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { Tooltip } from '../../components/ui/Tooltip'

interface Props {
  onTranscript: (text: string) => void
  /** Called with interim transcript text and listening state for live display */
  onLiveState?: (state: { isListening: boolean; transcript: string }) => void
}

export function VoiceButton({ onTranscript, onLiveState }: Props) {
  const { isListening, transcript, start, stop, isSupported } = useSpeechToText()
  const prevTranscript = useRef('')
  // Separate mic stream just for audio level visualization
  const [vizStream, setVizStream] = useState<MediaStream | null>(null)
  const level = useAudioLevel(vizStream)

  useEffect(() => {
    if (transcript && transcript !== prevTranscript.current) {
      prevTranscript.current = transcript
    }
  }, [transcript])

  // Push live state to parent for transcript display
  useEffect(() => {
    onLiveState?.({ isListening, transcript })
  }, [isListening, transcript, onLiveState])

  useEffect(() => {
    // When recording stops, emit the final transcript
    if (!isListening && prevTranscript.current) {
      onTranscript(prevTranscript.current)
      prevTranscript.current = ''
    }
  }, [isListening, onTranscript])

  // Open/close visualization mic stream in sync with recording
  useEffect(() => {
    if (isListening) {
      navigator.mediaDevices.getUserMedia({ audio: true }).then(setVizStream).catch(() => {})
    } else {
      if (vizStream) {
        vizStream.getTracks().forEach(t => t.stop())
        setVizStream(null)
      }
    }
    return () => {
      vizStream?.getTracks().forEach(t => t.stop())
    }
    // Only react to isListening changes — vizStream is managed, not a dependency
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isListening])

  if (!isSupported) return null

  return (
    <Tooltip content={isListening ? 'Stop recording' : 'Voice input'}>
      <button
        type="button"
        onClick={isListening ? stop : start}
        className={clsx(
          'flex items-center justify-center gap-1 rounded-sm p-2 transition-colors duration-fast',
          isListening
            ? 'bg-danger-dim text-danger'
            : 'text-content-tertiary hover:bg-surface-elevated hover:text-content-primary',
        )}
      >
        {isListening ? (
          <>
            <MicOff size={16} />
            <AudioLevelIndicator level={level} bars={3} className="h-4" />
          </>
        ) : (
          <Mic size={16} />
        )}
      </button>
    </Tooltip>
  )
}
