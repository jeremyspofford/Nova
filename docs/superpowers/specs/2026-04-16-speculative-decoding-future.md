# Speculative Decoding (Option C) — Future Spec

**Date:** 2026-04-16
**Status:** Future work — triggered when serving infrastructure changes (Ollama → vLLM/llama.cpp direct)

---

## Goal

2-3× faster token generation on the same hardware with identical output quality, via speculative decoding: a small "draft" model proposes tokens, a large "target" model verifies them in parallel.

## Trigger for doing this work

- You move off Ollama to vLLM, LMStudio, or llama.cpp direct (Ollama doesn't expose speculative decoding for qwen models yet)
- You get a larger GPU and want to run serious models locally at cloud-comparable speeds
- You notice streaming output rate is the bottleneck in user UX (you'd see this after Options A and B — if chat still feels slow, this is the next lever)

Don't pursue until you've already left Ollama for other reasons. It's not worth a serving-infra migration on its own.

---

## How It Works

- **Draft model** (small, fast — e.g., `llama3.2:1b`): proposes 4-5 tokens at a time
- **Target model** (big, slow — e.g., `qwen3.5:9b` or larger): verifies the proposed tokens in a single forward pass
- **Accept/reject**: tokens the target agrees with are accepted; first rejected token is replaced with the target's prediction
- **Net effect**: target model effectively generates N tokens per forward pass instead of 1, where N averages 2-5 depending on model agreement rate

Quality is **identical** to running the target alone — rejected draft tokens never appear in output. Only speedup.

## Engine support

| Engine | Speculative decoding support | Nova integration |
|---|---|---|
| Ollama | Partial — only llama.cpp's basic speculative for llama/mistral; qwen not supported as of 2026-04 | Blocked |
| vLLM | Full support via `--speculative-model` flag | Drop-in — just configure provider row with correct endpoint |
| llama.cpp direct | Full support via `--draft-model` flag | Requires new adapter (not OpenAI-compatible by default) |
| LMStudio | Recently added (check current version) | Drop-in like Ollama |
| TGI (HF) | Medusa-style, different approach | Drop-in |

## Integration with Nova

Minimal — once serving infra supports it, speculative decoding is pure server-side config. Nova's LLM client doesn't change; it just sees faster responses from the same provider endpoint.

Potential Nova-level additions (optional):
- Provider profile gains `is_speculative` boolean + `draft_model_ref` field (cosmetic — users see which providers are speculative-enabled in Settings)
- Metrics: track acceptance rate per provider (from engine telemetry) to surface tuning opportunities

---

## Draft/target pairing recommendations

Good pairings share vocabulary and style; the closer they are, the higher the acceptance rate. As of 2026-04:

| Target | Best draft | Expected acceptance rate |
|---|---|---|
| qwen3.5:9b | qwen3.5:1.5b | 65-75% |
| qwen3.5:14b | qwen3.5:3b | 70-80% |
| llama3.3:70b | llama3.2:1b | 60-70% |
| Claude Sonnet (cloud, n/a) | — | — |

If the draft model's VRAM footprint pushes total usage over your budget, speculative decoding is net-slower due to memory pressure. Check before enabling.

## 8GB VRAM on a 3060 Ti

Tight for target+draft:
- qwen3.5:9b (4-bit quant) ≈ 5.5GB
- qwen3.5:1.5b (4-bit quant) ≈ 1GB
- Total ≈ 6.5GB — leaves <2GB for context. Workable for short conversations, tight for long ones.

Realistic answer: speculative decoding on 8GB is marginal. 16GB+ is the sweet spot. **Trigger for doing this work is when you upgrade GPU.**

---

## Not in scope here

- Other serving-infra optimizations (Paged Attention, FlashAttention-2, batch size tuning) — those are adjacent and often land together with a vLLM migration, but they're separate knobs.
- Client-side (Nova app) changes — this is entirely a serving-layer concern.

## Estimated effort

Small if serving already supports it (~2 days: provider profile field + Settings display). Medium if you're simultaneously moving off Ollama (~1 week, mostly not about speculative decoding).
