"""
LLM provider routing.

Public API:
  route(db, purpose, messages, privacy_preference, _caller) -> LLMResult
  route_internal(db, purpose, messages, privacy_preference, _caller) -> str

_caller is injectable for testing; defaults to the real OpenAI-compatible call.
"""
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.llm_provider import LLMProviderProfile


class NoProvidersError(Exception):
    """No enabled LLMProviderProfile records exist in the database."""


class NoMatchingProvidersError(Exception):
    """Enabled providers exist but none match the requested privacy_preference."""


class AllProvidersFailed(Exception):
    """Every candidate provider raised an exception."""
    def __init__(self, last_error: Exception):
        self.last_error = last_error
        super().__init__(str(last_error))


@dataclass
class LLMResult:
    provider_id: str
    model_ref: str
    output: str


def route(
    db: Session,
    purpose: str,
    messages: list[dict],
    privacy_preference: str = "local_preferred",
    _caller=None,
) -> LLMResult:
    """Select a provider and call the LLM. Returns LLMResult.

    _caller(provider, messages) -> str  — injectable for tests; omit in production.
    """
    _caller = _caller or _call_provider_real

    providers = db.query(LLMProviderProfile).filter(
        LLMProviderProfile.enabled == True  # noqa: E712
    ).all()
    if not providers:
        raise NoProvidersError()

    candidates = _select_candidates(providers, privacy_preference)
    if not candidates:
        raise NoMatchingProvidersError()

    last_error: Exception | None = None
    for provider in candidates:
        try:
            output = _caller(provider, messages)
            return LLMResult(
                provider_id=provider.id,
                model_ref=provider.model_ref,
                output=output,
            )
        except Exception as exc:
            last_error = exc

    raise AllProvidersFailed(last_error)


def route_internal(
    db: Session,
    purpose: str,
    messages: list[dict],
    privacy_preference: str = "local_preferred",
    _caller=None,
) -> str:
    """Same as route() but returns just the output string.
    Used by tool handlers that need LLM access without an HTTP round-trip.
    """
    result = route(db, purpose, messages, privacy_preference, _caller)
    return result.output


def route_streaming(
    db: Session,
    purpose: str,
    messages: list[dict],
    privacy_preference: str = "local_preferred",
    _caller=None,
):
    """Validate provider selection eagerly, then return a chunk generator.

    Raises NoProvidersError / NoMatchingProvidersError immediately (before any
    yielding) so HTTP handlers can return a 4xx without opening the SSE stream.

    _caller(provider, messages) -> Iterator[str]  — injectable for tests.
    """
    _caller = _caller or _call_provider_streaming_real

    providers = db.query(LLMProviderProfile).filter(
        LLMProviderProfile.enabled == True  # noqa: E712
    ).all()
    if not providers:
        raise NoProvidersError()

    candidates = _select_candidates(providers, privacy_preference)
    if not candidates:
        raise NoMatchingProvidersError()

    return _stream_chunks(candidates[0], messages, _caller)


def _stream_chunks(provider, messages: list[dict], caller):
    """Inner generator — only called after route_streaming() validation passes."""
    yield from caller(provider, messages)


def _select_candidates(providers: list, privacy_preference: str) -> list:
    local = [p for p in providers if p.provider_type == "local"]
    cloud = [p for p in providers if p.provider_type == "cloud"]
    if privacy_preference == "local_required":
        return local
    elif privacy_preference == "local_preferred":
        return local + cloud
    else:  # cloud_allowed
        return cloud + local


def _call_provider_real(provider, messages: list[dict]) -> str:
    """Call the provider via OpenAI-compatible API. Used in production."""
    import os
    from openai import OpenAI

    if provider.provider_type == "local":
        api_key = "ollama"
    else:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Cloud provider selected but no OPENAI_API_KEY or ANTHROPIC_API_KEY is set"
            )

    client = OpenAI(base_url=provider.endpoint_ref, api_key=api_key)
    response = client.chat.completions.create(
        model=provider.model_ref,
        messages=messages,
    )
    return response.choices[0].message.content


def _call_provider_streaming_real(provider, messages: list[dict]):
    """Call provider with stream=True, yield content chunks."""
    import os
    from openai import OpenAI

    if provider.provider_type == "local":
        api_key = "ollama"
    else:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Cloud provider selected but no OPENAI_API_KEY or ANTHROPIC_API_KEY is set"
            )

    client = OpenAI(base_url=provider.endpoint_ref, api_key=api_key)
    stream = client.chat.completions.create(
        model=provider.model_ref,
        messages=messages,
        stream=True,
    )
    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content
