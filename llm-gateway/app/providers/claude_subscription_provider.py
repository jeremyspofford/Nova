"""
Claude Subscription Provider — uses claude.ai Max/Pro subscription quota.

Two auth paths (tried in order):
  1. CLAUDE_CODE_OAUTH_TOKEN env var  ← preferred, works in Docker
     Generate with: claude setup-token  (produces sk-ant-oat01-...)
  2. ~/.claude/.credentials.json  ← Linux only (macOS uses Keychain)

The OAuth token (sk-ant-oat01-...) is sent directly to api.anthropic.com
as a Bearer token. Billing is charged against your Max/Pro subscription
quota — NOT against an api.anthropic.com account balance. No CLI binary
required; runs natively inside Docker containers.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import AsyncIterator

import litellm
from nova_contracts import (
    CompleteRequest,
    CompleteResponse,
    EmbedRequest,
    EmbedResponse,
    ModelCapability,
    StreamChunk,
    ToolCall,
)

from app.providers.base import ModelProvider
from app.providers.utils import serialize_messages

log = logging.getLogger(__name__)

litellm.drop_params = True

# Map our namespaced model IDs → Anthropic API model names.
#
# Subscription OAuth (sk-ant-oat01-...) via the public /v1/messages API has
# limitations: 4.6 model aliases ("claude-sonnet-4-6") return a vague
# "invalid_request_error: Error" and no dated version has been found that works.
# Only claude-haiku-4-5-20251001 is confirmed working as of 2026-03.
#
# Claude Code itself works with 4.6 models because it uses a different internal
# API path, not the public messages endpoint. Until Anthropic publishes dated 4.6
# model names or fixes alias support for OAuth, we fall back to Haiku 4.5.
#
# TODO: Re-test when Anthropic updates their API. Track in TODOS.md.
_MODEL_MAP: dict[str, str] = {
    # Namespaced (claude-max/) → API name
    "claude-max/claude-haiku-4-5":      "claude-haiku-4-5-20251001",
    "claude-max/claude-sonnet-4-6":     "claude-haiku-4-5-20251001",  # fallback
    "claude-max/claude-opus-4-6":       "claude-haiku-4-5-20251001",  # fallback
    # Short aliases → dated
    "claude-haiku-4-5-20251001":        "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6":                "claude-haiku-4-5-20251001",  # fallback
    "claude-opus-4-6":                  "claude-haiku-4-5-20251001",  # fallback
}
_DEFAULT_API_MODEL = "claude-haiku-4-5-20251001"


def discover_claude_oauth_token() -> str | None:
    """
    Discover the Claude Max OAuth token from env or credentials file.
    Returns sk-ant-oat01-... token, or None if not found.
    """
    # 1. Explicit env var (highest priority — works in Docker without file mounts)
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if token:
        log.info("Claude Max: using token from CLAUDE_CODE_OAUTH_TOKEN")
        return token

    # 2. Linux credentials file  ~/.claude/.credentials.json
    # Note: macOS stores in Keychain — set CLAUDE_CODE_OAUTH_TOKEN there instead
    creds_path = Path.home() / ".claude" / ".credentials.json"
    if creds_path.exists():
        try:
            data = json.loads(creds_path.read_text())
            token = data.get("claudeAiOauth", {}).get("accessToken", "")
            if token:
                log.info("Claude Max: using token from %s", creds_path)
                return token
        except Exception as e:
            log.warning("Failed to read Claude credentials file: %s", e)

    # 3. macOS Keychain via `security` command (host dev only, not Docker)
    try:
        import subprocess
        result = subprocess.run(
            ["security", "find-generic-password", "-a", "Claude", "-s", "claude.ai", "-w"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            log.info("Claude Max: using token from macOS Keychain")
            return result.stdout.strip()
    except Exception:
        pass  # Keychain not available — expected inside Docker

    return None


class ClaudeSubscriptionProvider(ModelProvider):
    """
    Claude Max/Pro subscription adapter — calls api.anthropic.com with an
    OAuth token so usage is billed to your subscription, not to an API key.

    Uses LiteLLM under the hood; no CLI subprocess required.
    """

    def __init__(
        self,
        oauth_token: str | None = None,
        default_model: str = "claude-max/claude-sonnet-4-6",
    ):
        self._oauth_token = oauth_token or discover_claude_oauth_token()
        self._default_api_model = _MODEL_MAP.get(default_model, _DEFAULT_API_MODEL)
        if not self._oauth_token:
            log.warning(
                "ClaudeSubscriptionProvider: no OAuth token found. "
                "Run `claude setup-token` and set CLAUDE_CODE_OAUTH_TOKEN."
            )

    @property
    def name(self) -> str:
        return "claude-subscription"

    @property
    def capabilities(self) -> set[ModelCapability]:
        return {
            ModelCapability.chat,
            ModelCapability.streaming,
            ModelCapability.function_calling,
            ModelCapability.vision,
        }

    @property
    def is_available(self) -> bool:
        """True when an OAuth token is present — no binary required."""
        return bool(self._oauth_token)

    def _api_model(self, requested: str) -> str:
        """Resolve to a dated Anthropic model name with anthropic/ prefix for LiteLLM."""
        base = _MODEL_MAP.get(requested, self._default_api_model)
        # LiteLLM needs the anthropic/ prefix to identify the provider
        if not base.startswith("anthropic/"):
            return f"anthropic/{base}"
        return base

    async def complete(self, request: CompleteRequest) -> CompleteResponse:
        self._assert_available()

        messages = serialize_messages(request.messages)
        tools = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in request.tools
        ]

        kwargs: dict = {
            "model":       self._api_model(request.model),
            "messages":    messages,
            "temperature": request.temperature,
            "stream":      False,
            "api_key":     self._oauth_token,
        }
        if tools:
            kwargs["tools"] = tools
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens

        response = await litellm.acompletion(**kwargs)
        choice  = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments or "{}"),
                ))

        usage = response.usage
        cost  = litellm.completion_cost(completion_response=response) if usage else None

        return CompleteResponse(
            content=message.content or "",
            model=response.model,
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cost_usd=cost,
            finish_reason=choice.finish_reason or "stop",
        )

    async def stream(self, request: CompleteRequest) -> AsyncIterator[StreamChunk]:
        self._assert_available()

        messages = serialize_messages(request.messages)

        response = await litellm.acompletion(
            model=self._api_model(request.model),
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True,
            stream_options={"include_usage": True},
            api_key=self._oauth_token,
        )

        async for chunk in response:
            choice = chunk.choices[0] if chunk.choices else None
            content = ""
            finish_reason = None
            if choice:
                content = choice.delta.content or ""
                finish_reason = choice.finish_reason

            # Extract usage from final chunk (sent by LiteLLM when include_usage=True)
            input_tokens = None
            output_tokens = None
            cost = None
            usage = getattr(chunk, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", None)
                output_tokens = getattr(usage, "completion_tokens", None)
                try:
                    cost = litellm.completion_cost(completion_response=chunk)
                except Exception:
                    pass

            yield StreamChunk(
                delta=content,
                finish_reason=finish_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        raise NotImplementedError(
            "Claude does not expose embeddings. "
            "Use nomic-embed-text (Ollama) or text-embedding-004 (Gemini) instead."
        )
