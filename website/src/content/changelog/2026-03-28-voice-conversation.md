---
title: "Voice Chat & Conversation Mode"
date: 2026-03-28
---

- Voice service (`voice-service`, port 8130) -- STT via OpenAI Whisper, TTS via OpenAI TTS with provider abstraction for Deepgram and ElevenLabs
- Conversation mode on Brain page -- Gemini-style hands-free voice loop with auto-listen, silence detection, and barge-in interruption
- Barge-in support -- start talking while Nova is speaking to interrupt her mid-sentence; warm mic pattern eliminates turn-transition latency
- Live transcription -- real-time display of words as you speak (Web Speech API for live display, Whisper for final accuracy)
- Audio level visualization -- animated bars respond to mic input volume in real-time
- Mute now immediately stops TTS playback mid-sentence (previously only prevented new sentences)
- Model selector synced between Chat and Brain pages -- change model from either and it stays in sync
- Configurable voice settings: silence timeout (500ms-10s) and barge-in threshold (0.05-0.50) in Dashboard Settings
- Voice service is optional -- enable with `--profile voice`, dashboard auto-hides voice UI when unavailable
