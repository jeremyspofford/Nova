"""
Provider registry — maps model names to ModelProvider instances.
All providers are auto-detected from credentials on disk or env vars at startup.

SUBSCRIPTION AUTH (no API billing — uses your existing subscription quota)
─────────────────────────────────────────────────────────────────────────────
  Claude Max/Pro    Run `claude setup-token`, set CLAUDE_CODE_OAUTH_TOKEN
                    OR auto-read from ~/.claude/.credentials.json (Linux)
                    OR auto-read from macOS Keychain
                    → Models: claude-max/claude-sonnet-4-6, etc.

  ChatGPT Plus/Pro  Run `codex login`, then auto-read from ~/.codex/auth.json
                    OR set CHATGPT_ACCESS_TOKEN manually
                    → Models: chatgpt/gpt-4o, chatgpt/o3, etc.

FREE TIER API KEYS (no credit card required)
─────────────────────────────────────────────────────────────────────────────
  Ollama            Local, unlimited — always active
  Groq              14,400 req/day — set GROQ_API_KEY (console.groq.com)
  Gemini            250 req/day — set GEMINI_API_KEY (aistudio.google.com)
                    OR gcloud auth application-default login + GEMINI_USE_ADC=true
  Cerebras          1M tokens/day — set CEREBRAS_API_KEY (cloud.cerebras.ai)
  OpenRouter        50+ req/day — set OPENROUTER_API_KEY (openrouter.ai)
  GitHub Models     50-150 req/day — set GITHUB_TOKEN (github.com PAT)

PAID API KEYS
─────────────────────────────────────────────────────────────────────────────
  Anthropic API     set ANTHROPIC_API_KEY (console.anthropic.com)
  OpenAI API        set OPENAI_API_KEY (platform.openai.com)
"""
from __future__ import annotations

import logging
import os

from app.config import settings
from app.providers import (
    ChatGPTSubscriptionProvider,
    ClaudeSubscriptionProvider,
    FallbackProvider,
    GeminiADCProvider,
    LiteLLMProvider,
    ModelProvider,
    OllamaProvider,
    discover_chatgpt_token,
    discover_claude_oauth_token,
)

log = logging.getLogger(__name__)


def _inject_litellm_env_keys() -> None:
    """Inject configured API keys into environment for LiteLLM auto-detection."""
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.groq_api_key:
        os.environ["GROQ_API_KEY"] = settings.groq_api_key
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if settings.cerebras_api_key:
        os.environ["CEREBRAS_API_KEY"] = settings.cerebras_api_key
    if settings.openrouter_api_key:
        os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
    if settings.github_token:
        os.environ["GITHUB_TOKEN"] = settings.github_token


_inject_litellm_env_keys()


# ── Provider instances (stateless, created once at startup) ───────────────────
# Each provider reads its default model from settings so users can override via
# DEFAULT_GROQ_MODEL, DEFAULT_CEREBRAS_MODEL, etc. in their .env file.

_ollama = OllamaProvider(
    base_url=settings.ollama_base_url,
    default_model=settings.default_ollama_model,
)
_litellm = LiteLLMProvider()  # paid API fallback — model comes from request
_groq = LiteLLMProvider(default_model=settings.default_groq_model)
_cerebras = LiteLLMProvider(default_model=settings.default_cerebras_model)
_openrouter = LiteLLMProvider(default_model=settings.default_openrouter_model)
_github = LiteLLMProvider(default_model=settings.default_github_model)
_gemini = GeminiADCProvider(api_key=settings.gemini_api_key, use_adc=settings.gemini_use_adc)

# ── Subscription providers — auto-detect credentials at startup ────────────────

_claude_oauth_token = discover_claude_oauth_token()
_claude_subscription = ClaudeSubscriptionProvider(
    oauth_token=_claude_oauth_token,
    default_model=settings.default_claude_max_model,
)

_chatgpt_token = discover_chatgpt_token()
_chatgpt_subscription = ChatGPTSubscriptionProvider(
    access_token=_chatgpt_token,
    default_model=settings.default_chatgpt_model,
)

# Log what was found
if _claude_subscription.is_available:
    log.info("✓ Claude Max/Pro subscription active  → models: claude-max/*")
else:
    log.info("  Claude subscription not detected   (run `claude setup-token`, set CLAUDE_CODE_OAUTH_TOKEN)")

if _chatgpt_subscription.is_available:
    log.info("✓ ChatGPT Plus/Pro subscription active → models: chatgpt/*")
else:
    log.info("  ChatGPT subscription not detected  (run `codex login`)")


# ── Default fallback chain (cheapest/fastest → most capable) ──────────────────

def _build_default_fallback() -> FallbackProvider:
    chain: list[ModelProvider] = [_ollama]  # always local-first

    if settings.groq_api_key:
        chain.append(_groq)
    if settings.gemini_api_key or settings.gemini_use_adc:
        chain.append(_gemini)
    if settings.cerebras_api_key:
        chain.append(_cerebras)
    if settings.openrouter_api_key:
        chain.append(_openrouter)
    if settings.github_token:
        chain.append(_github)

    # Subscription providers come before paid API to prefer zero-cost
    if _claude_subscription.is_available:
        chain.append(_claude_subscription)
    if _chatgpt_subscription.is_available:
        chain.append(_chatgpt_subscription)

    if settings.anthropic_api_key or settings.openai_api_key:
        chain.append(_litellm)

    log.info("Default fallback chain: %d provider(s)", len(chain))
    return FallbackProvider(providers=chain)


_default_fallback = _build_default_fallback()


# ── Model → provider routing table ────────────────────────────────────────────
#
# Naming convention:
#   claude-max/*   → Claude subscription (no billing)
#   chatgpt/*      → ChatGPT subscription (no billing)
#   groq/*         → Groq free tier
#   gemini/*       → Gemini free tier
#   cerebras/*     → Cerebras free tier
#   openrouter/*   → OpenRouter (free models available)
#   github/*       → GitHub Models free tier
#   bare names     → Ollama (local)
#   claude-*/gpt-* without prefix → API key required (paid)

MODEL_REGISTRY: dict[str, ModelProvider] = {

    # ── Claude Max/Pro subscription ────────────────────────────────────────────
    "claude-max/claude-sonnet-4-6":       _claude_subscription,
    "claude-max/claude-opus-4-6":         _claude_subscription,
    "claude-max/claude-haiku-4-5":        _claude_subscription,

    # ── ChatGPT Plus/Pro subscription ─────────────────────────────────────────
    "chatgpt/gpt-4o":                     _chatgpt_subscription,
    "chatgpt/gpt-4o-mini":                _chatgpt_subscription,
    "chatgpt/o3":                         _chatgpt_subscription,
    "chatgpt/o4-mini":                    _chatgpt_subscription,
    "chatgpt/gpt-5.2-codex":             _chatgpt_subscription,
    "chatgpt/gpt-5.3-codex":             _chatgpt_subscription,

    # ── Local (Ollama) ─────────────────────────────────────────────────────────
    "llama3.2":                           _ollama,
    "llama3.2:3b":                        _ollama,
    "llama3.1":                           _ollama,
    "mistral":                            _ollama,
    "qwen2.5":                            _ollama,
    "phi4":                               _ollama,
    "deepseek-r1":                        _ollama,
    "gemma3":                             _ollama,

    # ── Groq — 14,400 req/day free ────────────────────────────────────────────
    "groq/llama-3.3-70b-versatile":       _groq,
    "groq/llama-3.1-8b-instant":          _groq,
    "groq/mixtral-8x7b-32768":            _groq,
    "groq/llama-3.2-3b-preview":          _groq,

    # ── Gemini — 250 req/day free ─────────────────────────────────────────────
    "gemini/gemini-2.5-flash":            _gemini,
    "gemini/gemini-2.5-pro":              _gemini,
    "gemini-2.5-flash":                   _gemini,

    # ── Cerebras — 1M tokens/day free ─────────────────────────────────────────
    # As of 2026, only llama3.1-8b is confirmed active on free tier.
    # llama3.3-70b and llama3.1-70b have been retired from Cerebras Cloud.
    "cerebras/llama3.1-8b":              _cerebras,
    "cerebras/llama-3.1-8b":            _cerebras,   # alias for LiteLLM model name

    # ── OpenRouter — free models available ────────────────────────────────────
    "openrouter/meta-llama/llama-3.1-8b-instruct:free": _openrouter,
    "openrouter/google/gemma-2-9b-it:free":             _openrouter,
    "openrouter/mistralai/mistral-7b-instruct:free":    _openrouter,

    # ── GitHub Models — 50-150 req/day free ───────────────────────────────────
    "github/gpt-4o-mini":                 _github,
    "github/meta-llama-3.1-70b-instruct": _github,

    # ── Paid Anthropic API (bare model names route here when no subscription) ──
    # If a Claude subscription IS active, use claude-max/* prefix to use it.
    "claude-sonnet-4-6":                  _claude_subscription if _claude_oauth_token else _litellm,
    "claude-opus-4-6":                    _claude_subscription if _claude_oauth_token else _litellm,
    "claude-haiku-4-5-20251001":          _litellm,

    # ── Paid OpenAI API ────────────────────────────────────────────────────────
    # Use chatgpt/* prefix to route to subscription instead.
    "gpt-4o":                             _litellm,
    "gpt-4o-mini":                        _litellm,

    # ── Embedding models ──────────────────────────────────────────────────────
    "nomic-embed-text":                   _ollama,     # local, free, 768-dim
    "text-embedding-004":                 _gemini,     # Gemini free tier
    "text-embedding-3-small":             _litellm,    # OpenAI paid

    # ── Catch-all: smart fallback across all configured providers ──────────────
    "__default__":                        _default_fallback,
}


def get_provider(model: str) -> ModelProvider:
    """Look up the provider for a model ID, falling back to __default__."""
    provider = MODEL_REGISTRY.get(model) or MODEL_REGISTRY["__default__"]
    if model not in MODEL_REGISTRY:
        log.warning("Unknown model '%s', using default fallback provider", model)
    return provider
