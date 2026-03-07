import { useState, useCallback, useRef, useEffect } from 'react'

interface SpeechToText {
  isListening: boolean
  transcript: string
  start: () => void
  stop: () => void
  isSupported: boolean
}

const SpeechRecognition =
  typeof window !== 'undefined'
    ? (window as unknown as Record<string, unknown>).SpeechRecognition ??
      (window as unknown as Record<string, unknown>).webkitSpeechRecognition
    : null

export function useSpeechToText(): SpeechToText {
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)

  const isSupported = !!SpeechRecognition

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
    setIsListening(false)
  }, [])

  const start = useCallback(() => {
    if (!SpeechRecognition) return
    setTranscript('')
    const recognition = new (SpeechRecognition as new () => SpeechRecognitionInstance)()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let text = ''
      for (let i = 0; i < event.results.length; i++) {
        text += event.results[i][0].transcript
      }
      setTranscript(text)
    }

    recognition.onerror = () => {
      setIsListening(false)
    }

    recognition.onend = () => {
      setIsListening(false)
    }

    recognitionRef.current = recognition as SpeechRecognitionInstance
    recognition.start()
    setIsListening(true)
  }, [])

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop()
    }
  }, [])

  return { isListening, transcript, start, stop, isSupported }
}

// Minimal type shims for Web Speech API
interface SpeechRecognitionEvent {
  results: SpeechRecognitionResultList
}
interface SpeechRecognitionResultList {
  length: number
  [index: number]: { [index: number]: { transcript: string } }
}
interface SpeechRecognitionInstance {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: unknown) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
}
