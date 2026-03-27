import { useState, useEffect, useRef } from 'react'

/**
 * Returns a 0–1 audio level from a MediaStream using Web Audio AnalyserNode.
 * When stream is null, level stays at 0 and no resources are allocated.
 */
export function useAudioLevel(stream: MediaStream | null): number {
  const [level, setLevel] = useState(0)
  const ctxRef = useRef<AudioContext | null>(null)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    if (!stream) {
      setLevel(0)
      return
    }

    const ctx = new AudioContext()
    ctxRef.current = ctx
    const source = ctx.createMediaStreamSource(stream)
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    analyser.smoothingTimeConstant = 0.4
    source.connect(analyser)

    const buf = new Uint8Array(analyser.frequencyBinCount)

    const poll = () => {
      analyser.getByteFrequencyData(buf)
      // RMS of frequency bins, normalized to 0–1
      let sum = 0
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
      const rms = Math.sqrt(sum / buf.length) / 255
      // Boost low volumes so quiet speech is visible
      setLevel(Math.min(1, rms * 2.5))
      rafRef.current = requestAnimationFrame(poll)
    }
    rafRef.current = requestAnimationFrame(poll)

    return () => {
      cancelAnimationFrame(rafRef.current)
      source.disconnect()
      ctx.close()
      ctxRef.current = null
      setLevel(0)
    }
  }, [stream])

  return level
}
