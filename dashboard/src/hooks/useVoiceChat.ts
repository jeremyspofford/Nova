import { useState, useRef, useCallback, useEffect } from 'react'

interface UseVoiceChatOptions {
  onTranscript?: (text: string) => void
  onError?: (error: string) => void
  maxDurationMs?: number
  minDurationMs?: number
}

interface SentenceAudio {
  seq: number
  audio: HTMLAudioElement | null
  blobUrl: string | null
  status: 'pending' | 'loading' | 'ready' | 'playing' | 'done'
}

export function useVoiceChat({
  onTranscript,
  onError,
  maxDurationMs = 60_000,
  minDurationMs = 500,
}: UseVoiceChatOptions = {}) {
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [recordingDuration, setRecordingDuration] = useState(0)
  const [voiceAvailable, setVoiceAvailable] = useState(false)
  const [muted, setMuted] = useState(() => localStorage.getItem('nova_voice_muted') === 'true')
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const mimeTypeRef = useRef('audio/webm;codecs=opus')
  const recordStartRef = useRef(0)
  const durationIntervalRef = useRef<ReturnType<typeof setInterval>>()
  const maxDurationTimerRef = useRef<ReturnType<typeof setTimeout>>()

  // Audio playback queue
  const audioQueueRef = useRef<SentenceAudio[]>([])
  const currentSeqRef = useRef(0)
  const nextSeqRef = useRef(0)
  const sentenceBufferRef = useRef('')
  const inCodeBlockRef = useRef(false)

  // Check voice service availability
  useEffect(() => {
    const check = async () => {
      try {
        const resp = await fetch('/voice-api/health/ready')
        if (resp.ok) {
          const data = await resp.json()
          setVoiceAvailable(data.stt_available && data.tts_available)
        }
      } catch {
        setVoiceAvailable(false)
      }
    }
    check()
    const interval = setInterval(check, 30_000)
    return () => clearInterval(interval)
  }, [])

  // Persist mute state
  useEffect(() => {
    localStorage.setItem('nova_voice_muted', String(muted))
  }, [muted])

  // Detect supported MIME type
  useEffect(() => {
    const types = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']
    for (const type of types) {
      if (MediaRecorder.isTypeSupported(type)) {
        mimeTypeRef.current = type
        break
      }
    }
  }, [])

  const stopAllPlayback = useCallback(() => {
    audioQueueRef.current.forEach(item => {
      if (item.audio) {
        item.audio.pause()
        item.audio.currentTime = 0
      }
      if (item.blobUrl) URL.revokeObjectURL(item.blobUrl)
    })
    audioQueueRef.current = []
    currentSeqRef.current = 0
    nextSeqRef.current = 0
    sentenceBufferRef.current = ''
    inCodeBlockRef.current = false
    setIsSpeaking(false)
  }, [])

  // Immediately stop playback when muted
  useEffect(() => {
    if (muted) stopAllPlayback()
  }, [muted, stopAllPlayback])

  const startRecording = useCallback(async () => {
    // Interrupt any playing audio first
    stopAllPlayback()

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      })

      setMediaStream(stream)  // expose for audio level visualization
      const recorder = new MediaRecorder(stream, { mimeType: mimeTypeRef.current })
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        setMediaStream(null)
        clearInterval(durationIntervalRef.current)
        clearTimeout(maxDurationTimerRef.current)

        const elapsed = Date.now() - recordStartRef.current
        if (elapsed < minDurationMs) {
          setIsRecording(false)
          return // Too short, ignore
        }

        const blob = new Blob(chunksRef.current, { type: mimeTypeRef.current })
        setIsRecording(false)
        setIsTranscribing(true)

        try {
          const formData = new FormData()
          formData.append('file', blob, `recording.${mimeTypeRef.current.split('/')[1].split(';')[0]}`)
          formData.append('format', mimeTypeRef.current.split('/')[1].split(';')[0])

          const resp = await fetch('/voice-api/api/v1/voice/transcribe', {
            method: 'POST',
            body: formData,
          })

          if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: 'Transcription failed' }))
            throw new Error(err.detail || `HTTP ${resp.status}`)
          }

          const result = await resp.json()
          if (result.text) {
            onTranscript?.(result.text)
          } else {
            onError?.("Couldn't understand that — try again")
          }
        } catch (err: any) {
          onError?.(err.message || 'Transcription failed — try again or type your message')
        } finally {
          setIsTranscribing(false)
        }
      }

      recorder.start()
      recordStartRef.current = Date.now()
      setIsRecording(true)
      setRecordingDuration(0)
      mediaRecorderRef.current = recorder

      // Duration counter
      durationIntervalRef.current = setInterval(() => {
        setRecordingDuration(Date.now() - recordStartRef.current)
      }, 100)

      // Auto-stop at max duration
      maxDurationTimerRef.current = setTimeout(() => {
        if (mediaRecorderRef.current?.state === 'recording') {
          mediaRecorderRef.current.stop()
        }
      }, maxDurationMs)
    } catch (err: any) {
      if (err.name === 'NotAllowedError') {
        onError?.('Microphone access denied. Enable in browser settings.')
      } else {
        onError?.(err.message || 'Could not access microphone')
      }
    }
  }, [stopAllPlayback, minDurationMs, maxDurationMs, onTranscript, onError])

  const stopRecording = useCallback(() => {
    const elapsed = Date.now() - recordStartRef.current
    if (elapsed < minDurationMs) return // Ignore too-quick stops

    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }, [minDurationMs])

  const toggleRecording = useCallback(() => {
    if (isRecording) stopRecording()
    else startRecording()
  }, [isRecording, startRecording, stopRecording])

  // ── TTS Playback ──────────────────────────────────────────────

  const playNextInQueue = useCallback(() => {
    const next = audioQueueRef.current.find(
      item => item.seq === currentSeqRef.current && item.status === 'ready'
    )
    if (!next || !next.audio) return

    next.status = 'playing'
    setIsSpeaking(true)

    next.audio.onended = () => {
      next.status = 'done'
      if (next.blobUrl) URL.revokeObjectURL(next.blobUrl)
      currentSeqRef.current++

      // Check if more to play
      const hasMore = audioQueueRef.current.some(
        item => item.seq >= currentSeqRef.current && item.status !== 'done'
      )
      if (!hasMore) {
        setIsSpeaking(false)
        audioQueueRef.current = []
        currentSeqRef.current = 0
        nextSeqRef.current = 0
      } else {
        playNextInQueue()
      }
    }

    if (!muted) {
      next.audio.play().catch(() => {
        // Autoplay blocked — skip this sentence
        next.status = 'done'
        currentSeqRef.current++
        playNextInQueue()
      })
    } else {
      // Muted — skip immediately
      next.status = 'done'
      if (next.blobUrl) URL.revokeObjectURL(next.blobUrl)
      currentSeqRef.current++
      playNextInQueue()
    }
  }, [muted])

  const synthesizeSentence = useCallback(async (text: string, seq: number) => {
    const entry: SentenceAudio = { seq, audio: null, blobUrl: null, status: 'loading' }
    audioQueueRef.current.push(entry)

    try {
      const resp = await fetch('/voice-api/api/v1/voice/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: 'nova', model: 'tts-1' }),
      })
      if (!resp.ok) throw new Error(`TTS failed: ${resp.status}`)

      const blob = await resp.blob()
      const blobUrl = URL.createObjectURL(blob)
      const audio = new Audio(blobUrl)

      entry.audio = audio
      entry.blobUrl = blobUrl
      entry.status = 'ready'

      // Try to play if this is the current sequence
      if (entry.seq === currentSeqRef.current) {
        playNextInQueue()
      }
    } catch {
      // TTS failed for this sentence — mark done, skip it
      entry.status = 'done'
    }
  }, [playNextInQueue])

  // ── Text-to-speakable preprocessor ────────────────────────────

  const toSpeakable = useCallback((text: string): string => {
    let result = text
    // Remove fenced code blocks entirely
    result = result.replace(/```[\s\S]*?```/g, ' Here\'s some code. ')
    // Remove inline code backticks (keep content)
    result = result.replace(/`([^`]+)`/g, '$1')
    // Replace URLs with domain
    result = result.replace(/https?:\/\/([^\s/]+)[^\s]*/g, 'link to $1')
    // Remove markdown tables
    result = result.replace(/\|[^\n]+\|(\n\|[-:| ]+\|)?(\n\|[^\n]+\|)*/g, '')
    // Remove heading markers
    result = result.replace(/^#{1,6}\s+/gm, '')
    // Remove bold/italic markers
    result = result.replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1')
    result = result.replace(/_{1,2}([^_]+)_{1,2}/g, '$1')
    // Remove list markers
    result = result.replace(/^[\s]*[-*]\s+/gm, '')
    result = result.replace(/^[\s]*\d+\.\s+/gm, '')
    // Remove horizontal rules
    result = result.replace(/^---+$/gm, '')
    // Clean up multiple spaces/newlines
    result = result.replace(/\n{2,}/g, '\n').replace(/\s{2,}/g, ' ').trim()
    return result
  }, [])

  // ── Sentence detection + buffer ───────────────────────────────

  const feedText = useCallback((delta: string) => {
    if (muted) return // Don't buffer if muted

    sentenceBufferRef.current += delta

    // Track code blocks
    const fences = (sentenceBufferRef.current.match(/```/g) || []).length
    inCodeBlockRef.current = fences % 2 !== 0
    if (inCodeBlockRef.current) return // Don't split inside code blocks

    // Check for sentence boundaries
    const buf = sentenceBufferRef.current
    const delimiters = /[.!?]\s|[\n]/
    const match = buf.match(delimiters)

    if (match && match.index !== undefined) {
      const boundary = match.index + match[0].length
      const sentence = buf.slice(0, boundary).trim()
      sentenceBufferRef.current = buf.slice(boundary)

      if (sentence) {
        const speakable = toSpeakable(sentence)
        if (speakable.trim()) {
          synthesizeSentence(speakable, nextSeqRef.current++)
        }
      }
    }

    // Max-length fallback
    if (buf.length > 200 && !inCodeBlockRef.current) {
      const sentence = buf.trim()
      sentenceBufferRef.current = ''
      if (sentence) {
        const speakable = toSpeakable(sentence)
        if (speakable.trim()) {
          synthesizeSentence(speakable, nextSeqRef.current++)
        }
      }
    }
  }, [muted, toSpeakable, synthesizeSentence])

  const flushBuffer = useCallback(() => {
    const remaining = sentenceBufferRef.current.trim()
    sentenceBufferRef.current = ''
    inCodeBlockRef.current = false
    if (remaining && !muted) {
      const speakable = toSpeakable(remaining)
      if (speakable.trim()) {
        synthesizeSentence(speakable, nextSeqRef.current++)
      }
    }
  }, [muted, toSpeakable, synthesizeSentence])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopAllPlayback()
      clearInterval(durationIntervalRef.current)
      clearTimeout(maxDurationTimerRef.current)
    }
  }, [stopAllPlayback])

  return {
    // Recording
    isRecording,
    isTranscribing,
    recordingDuration,
    toggleRecording,
    // Playback
    isSpeaking,
    muted,
    setMuted,
    feedText,      // Call with each text delta during streaming
    flushBuffer,   // Call when stream ends
    stopAllPlayback,
    // State
    voiceAvailable,
    mediaStream,   // Live MediaStream during recording (for audio level visualization)
  }
}
