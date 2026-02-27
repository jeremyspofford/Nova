"""
LLM Gateway contracts — ModelProvider interface.
Any provider implementing these contracts can be swapped without touching consumers.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field


class ModelCapability(str, Enum):
    chat = "chat"
    streaming = "streaming"
    function_calling = "function_calling"
    vision = "vision"
    embeddings = "embeddings"
    structured_output = "structured_output"


class ToolCallRef(BaseModel):
    """Tool invocation embedded in an assistant message.
    Separate from ToolCall (which is used in CompleteResponse) so that
    message history can carry the LLM's tool-call requests forward."""
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: str  # system | user | assistant | tool
    content: str = ""          # empty is valid for pure tool-call assistant turns
    name: str | None = None    # identifies which tool produced a result (role=tool)
    tool_call_id: str | None = None   # ties a tool result back to a ToolCallRef
    tool_calls: list[ToolCallRef] | None = None  # present on assistant turns that invoke tools


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


class CompleteRequest(BaseModel):
    model: str
    messages: list[Message]
    tools: list[ToolDefinition] = Field(default_factory=list)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)  # agent_id, task_id for cost tracking


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class CompleteResponse(BaseModel):
    content: str
    model: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    finish_reason: str  # stop | tool_calls | length | content_filter


class StreamChunk(BaseModel):
    delta: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None


class EmbedRequest(BaseModel):
    model: str
    texts: list[str]
    dimensions: int = 768  # Default per Part 3 recommendation


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    input_tokens: int


class ModelInfo(BaseModel):
    id: str
    provider: str
    capabilities: list[ModelCapability]
    context_window: int
    max_output_tokens: int
    cost_per_input_token: float | None = None
    cost_per_output_token: float | None = None
