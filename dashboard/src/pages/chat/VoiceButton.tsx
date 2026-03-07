import { Mic, MicOff } from 'lucide-react'
import { useSpeechToText } from '../../hooks/useSpeechToText'
import { useEffect, useRef } from 'react'

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
    <button
      type="button"
      onClick={isListening ? stop : start}
      title={isListening ? 'Stop recording' : 'Voice input'}
      className={`flex items-center justify-center rounded-lg p-2 transition-colors ${
        isListening
          ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400'
          : 'text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800'
      }`}
    >
      {isListening ? (
        <MicOff size={16} className="animate-pulse" />
      ) : (
        <Mic size={16} />
      )}
    </button>
  )
}
