"""
Translation layer: OpenAI API format ↔ Nova internal contracts.

Allows VS Code Continue.dev, Cursor, and any OpenAI-compatible client to
connect to the Nova LLM Gateway without modification. Users configure their
client to point at http://localhost:8001/v1 and use Nova model IDs directly.
"""
from __future__ import annotations

import time
from uuid import uuid4

from pydantic import BaseModel, Field

from nova_contracts import CompleteRequest, CompleteResponse, Message


# ── OpenAI request shapes ─────────────────────────────────────────────────────

class OAIMessage(BaseModel):
    role: str
    content: str | None = None
    name: str | None = None


class OAIChatCompletionRequest(BaseModel):
    model: str
    messages: list[OAIMessage]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = None
    stream: bool = False
    # Extra OpenAI fields (top_p, n, stop, frequency_penalty, etc.) are silently ignored
    model_config = {"extra": "ignore"}


# ── OpenAI response shapes ────────────────────────────────────────────────────

class OAIUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class OAIMessageResponse(BaseModel):
    role: str = "assistant"
    content: str


class OAIChoice(BaseModel):
    index: int = 0
    message: OAIMessageResponse
    finish_reason: str


class OAIChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[OAIChoice]
    usage: OAIUsage


# ── OpenAI streaming shapes ───────────────────────────────────────────────────

class OAIStreamDelta(BaseModel):
    role: str | None = None
    content: str | None = None


class OAIStreamChoice(BaseModel):
    index: int = 0
    delta: OAIStreamDelta
    finish_reason: str | None = None


class OAIStreamChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[OAIStreamChoice]


# ── Translation functions ─────────────────────────────────────────────────────

def oai_request_to_nova(req: OAIChatCompletionRequest) -> CompleteRequest:
    """Map an OpenAI chat completion request to a Nova CompleteRequest."""
    return CompleteRequest(
        model=req.model,
        messages=[Message(role=m.role, content=m.content or "") for m in req.messages],
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        stream=req.stream,
    )


def nova_response_to_oai(
    response: CompleteResponse,
    request_model: str,
) -> OAIChatCompletionResponse:
    """Map a Nova CompleteResponse to OpenAI ChatCompletion format.

    Echoes request_model (not response.model) so clients that use Nova model
    IDs like 'claude-max/claude-sonnet-4-6' get back exactly what they sent,
    avoiding confusion from internal routing identifiers.
    """
    return OAIChatCompletionResponse(
        id=f"chatcmpl-{uuid4().hex[:24]}",
        created=int(time.time()),
        model=request_model,
        choices=[
            OAIChoice(
                message=OAIMessageResponse(content=response.content),
                finish_reason=response.finish_reason,
            )
        ],
        usage=OAIUsage(
            prompt_tokens=response.input_tokens,
            completion_tokens=response.output_tokens,
            total_tokens=response.input_tokens + response.output_tokens,
        ),
    )


def make_stream_chunk(
    delta_text: str,
    chunk_id: str,
    model: str,
    finish_reason: str | None = None,
) -> OAIStreamChunk:
    """Build a single OpenAI-format streaming chunk from a Nova stream delta."""
    return OAIStreamChunk(
        id=chunk_id,
        created=int(time.time()),
        model=model,
        choices=[
            OAIStreamChoice(
                delta=OAIStreamDelta(content=delta_text),
                finish_reason=finish_reason,
            )
        ],
    )
