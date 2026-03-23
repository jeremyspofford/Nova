"""
Base agent class shared by all quartet pipeline agents.

Every agent:
  1. Receives a PipelineState (accumulated outputs from prior stages)
  2. Builds a message list for the LLM
  3. Calls think_json() to get a structured response with automatic retry-on-bad-JSON
  4. Returns a typed output dict

The think_json() retry pattern (from arialabs/nova):
  - Attempt 1: send messages, parse JSON
  - On parse failure: append {role:assistant, bad_output} + {role:user, corrective_msg}
  - Attempt 2: LLM now sees its own mistake and the correction instruction
  - This is significantly more effective than re-sending the same prompt
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

THINK_JSON_MAX_ATTEMPTS = 2


# ── Pipeline state ─────────────────────────────────────────────────────────────

@dataclass
class PipelineState:
    """Accumulated context as each agent in the pipeline completes."""
    task_input: str                             # original user request
    completed: dict[str, Any] = field(default_factory=dict)   # role → output dict
    flags: set[str]            = field(default_factory=set)    # "guardrail_blocked", etc.
    task_tags: list[str]       = field(default_factory=list)   # ["code", "config", …]
    complexity: str | None     = None                          # "simple", "moderate", "complex"


# ── Run condition evaluator ────────────────────────────────────────────────────

def should_agent_run(condition: dict | None, state: PipelineState) -> bool:
    """
    Evaluate a run_condition JSONB dict against the current pipeline state.
    Returns True if the agent should run, False to skip it.

    Supported condition types:
      {"type": "always"}                                    → always run (default)
      {"type": "never"}                                     → soft-disable
      {"type": "on_flag",  "flag":  "guardrail_blocked"}   → run if flag is set
      {"type": "has_tag",  "tag":   "code"}                → run if task has this tag
      {"type": "on_pass"}                                   → run if code_review passed
      {"type": "on_fail"}                                   → run if any failure flag set
      {"type": "and", "conditions": [...]}                  → all must be true
      {"type": "or",  "conditions": [...]}                  → any must be true
    """
    if not condition:
        return True

    ctype = condition.get("type", "always")

    if ctype == "always":
        return True
    if ctype == "never":
        return False
    if ctype == "on_flag":
        return condition.get("flag", "") in state.flags
    if ctype == "not_flag":
        return condition.get("flag", "") not in state.flags
    if ctype == "has_tag":
        return condition.get("tag", "") in state.task_tags
    if ctype == "on_pass":
        return "code_review_passed" in state.flags
    if ctype == "on_fail":
        return bool(state.flags & {"guardrail_blocked", "code_review_rejected"})
    if ctype == "and":
        return all(should_agent_run(c, state) for c in condition.get("conditions", []))
    if ctype == "or":
        return any(should_agent_run(c, state) for c in condition.get("conditions", []))

    logger.warning(f"Unknown run_condition type '{ctype}' — defaulting to run")
    return True


# ── Base agent ────────────────────────────────────────────────────────────────

class BaseAgent:
    """
    Base class for all pipeline agents.

    Subclasses implement:
      - ROLE: str            class-level role name
      - DEFAULT_SYSTEM: str  fallback system prompt if pod_agents.system_prompt is null
      - async run(state, agent_cfg, task_id) → dict
    """

    ROLE: str = "base"
    DEFAULT_SYSTEM: str = "You are a helpful AI agent."

    def __init__(
        self,
        model: str,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        fallback_models: list[str] | None = None,
        tier: str | None = None,
        task_type: str | None = None,
    ) -> None:
        self.model          = model
        self.system_prompt  = system_prompt or self.DEFAULT_SYSTEM
        self.allowed_tools  = allowed_tools  # None = all tools; [] = no tools
        self.temperature    = temperature
        self.max_tokens     = max_tokens
        self.fallback_models = fallback_models or []
        self.tier           = tier       # Routing tier hint for llm-gateway
        self.task_type      = task_type  # Task type for outcome tracking
        # Usage accumulator — populated by _call_llm_full()
        self._usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "llm_calls": 0}
        # Training data log — populated by _call_llm_full() when training logging is enabled
        self._training_log: list[dict] = []

    # ── LLM call ──────────────────────────────────────────────────────────────

    async def _call_llm_full(self, messages: list[dict]) -> tuple[str, str]:
        """
        Call the LLM gateway and return (content, model_used).

        Tries self.model first, then each entry in self.fallback_models in order.
        Accumulates token usage into self._usage and appends to self._training_log.
        """
        from ...clients import get_llm_client

        client = get_llm_client()
        models_to_try = [self.model, *self.fallback_models]
        last_exc: Exception | None = None

        for model in models_to_try:
            try:
                payload = {
                    "model":       model,
                    "messages":    messages,
                    "temperature": self.temperature,
                    "max_tokens":  self.max_tokens,
                }
                if self.tier:
                    payload["tier"] = self.tier
                if self.task_type:
                    payload["task_type"] = self.task_type
                response = await client.post("/complete", json=payload)
                response.raise_for_status()
                data = response.json()
                was_fallback = model != self.model
                if was_fallback:
                    logger.warning(
                        "[%s] Primary model '%s' failed — used fallback '%s'",
                        self.ROLE, self.model, model,
                    )

                # Use the gateway's resolved model (handles tier routing / auto)
                resolved_model = data.get("model") or model

                # Accumulate usage
                in_tokens = data.get("input_tokens", 0) or 0
                out_tokens = data.get("output_tokens", 0) or 0
                cost = data.get("cost_usd", 0.0) or 0.0
                self._usage["input_tokens"] += in_tokens
                self._usage["output_tokens"] += out_tokens
                self._usage["cost_usd"] += cost
                self._usage["llm_calls"] += 1
                self._usage["model"] = resolved_model

                content = data["content"]

                # Training log entry
                self._training_log.append({
                    "messages": messages,
                    "response": content,
                    "model": resolved_model,
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "cost_usd": cost,
                    "was_fallback": was_fallback,
                    "temperature": self.temperature,
                })

                return content, resolved_model
            except Exception as exc:
                last_exc = exc
                logger.warning("[%s] Model '%s' failed: %s", self.ROLE, model, exc)

        raise RuntimeError(
            f"[{self.ROLE}] All models failed. "
            f"Primary='{self.model}' fallbacks={self.fallback_models}. "
            f"Last error: {last_exc}"
        ) from last_exc

    async def _call_llm(self, messages: list[dict]) -> str:
        """Call the LLM gateway and return the raw text response."""
        content, _ = await self._call_llm_full(messages)
        return content

    # ── think_json ────────────────────────────────────────────────────────────

    async def think_json(self, messages: list[dict], purpose: str = "") -> dict:
        """
        Call the LLM and parse the response as JSON.

        On parse failure: appends the bad response as an assistant turn + a
        corrective user turn and retries once. The model sees its own mistake
        and the explicit correction instruction — much more effective than
        blind retry.
        """
        for attempt in range(THINK_JSON_MAX_ATTEMPTS):
            raw = await self._call_llm(messages)

            # Strip markdown code fences if the model wrapped the JSON
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                cleaned = "\n".join(
                    l for l in lines
                    if not l.strip().startswith("```")
                ).strip()

            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as exc:
                if attempt + 1 >= THINK_JSON_MAX_ATTEMPTS:
                    logger.error(
                        f"[{self.ROLE}] think_json failed after {THINK_JSON_MAX_ATTEMPTS} "
                        f"attempts{' ('+purpose+')' if purpose else ''}: {exc}"
                    )
                    raise ValueError(
                        f"Agent {self.ROLE} could not produce valid JSON: {exc}"
                    ) from exc

                logger.warning(
                    f"[{self.ROLE}] JSON parse error on attempt {attempt + 1}, retrying with feedback"
                )
                # Append bad output + corrective message before retry
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was not valid JSON ({exc}). "
                            "Please respond ONLY with valid JSON — no markdown fences, "
                            "no preamble, no explanation. Just the JSON object."
                        ),
                    },
                ]

        raise RuntimeError("think_json: unreachable")   # satisfies type checker

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _system_message(self) -> dict:
        return {"role": "system", "content": self.system_prompt}

    @staticmethod
    def _user_message(content: str) -> dict:
        return {"role": "user", "content": content}

    @staticmethod
    def _elapsed(start: float) -> int:
        """Return milliseconds since start."""
        return int((time.monotonic() - start) * 1000)
