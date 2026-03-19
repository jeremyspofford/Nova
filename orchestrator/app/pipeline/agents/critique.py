"""Two-phase Critique agents: Direction gate + Acceptance test."""
from __future__ import annotations

import json
import logging
from typing import Any

from .base import BaseAgent, PipelineState

logger = logging.getLogger(__name__)


class CritiqueDirectionAgent(BaseAgent):
    ROLE = "critique_direction"
    DEFAULT_SYSTEM = (
        "You are a Critique-Direction agent. Evaluate whether the Task Agent's output "
        "is attempting the right thing.\n\n"
        "Compare the original user request against the Task Agent's output. "
        "Respond with EXACTLY ONE of these JSON objects:\n"
        '1. If on track: {"verdict": "approved"}\n'
        '2. If wrong/incomplete: {"verdict": "needs_revision", "feedback": "..."}\n'
        '3. If too ambiguous: {"verdict": "needs_clarification", "questions": ["..."]}\n'
        "Respond ONLY with the JSON object."
    )

    async def run(self, state: PipelineState, agent_cfg=None, task_id: str = "", **kwargs) -> dict[str, Any]:
        task_output = state.completed.get("task", {})
        user_content = f"## Original Request\n{state.task_input}\n\n## Task Agent Output\n{json.dumps(task_output, indent=2)}"

        # Include prior clarification answers if available
        critique_feedback = state.completed.get("_critique_feedback")
        if critique_feedback:
            user_content += f"\n\n## Previous Critique Feedback\n{critique_feedback}"

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        content, _model = await self._call_llm_full(messages)
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            logger.warning("Critique-Direction returned non-JSON — defaulting to approved")
            return {"verdict": "approved"}


class CritiqueAcceptanceAgent(BaseAgent):
    ROLE = "critique_acceptance"
    DEFAULT_SYSTEM = (
        "You are a Critique-Acceptance agent — the final quality gate. "
        "Does the output completely and correctly fulfill the original request?\n\n"
        "The output has passed security (Guardrail) and code quality (Code Review). "
        "Check REQUIREMENT FULFILLMENT only.\n\n"
        "Respond with EXACTLY ONE JSON object:\n"
        '1. If fully met: {"verdict": "pass"}\n'
        '2. If not met: {"verdict": "fail", "feedback": "..."}\n'
        "Respond ONLY with the JSON object."
    )

    async def run(self, state: PipelineState, agent_cfg=None, task_id: str = "", **kwargs) -> dict[str, Any]:
        task_output = state.completed.get("task", {})
        user_content = f"## Original Request\n{state.task_input}\n\n## Final Output\n{json.dumps(task_output, indent=2)}"

        acceptance_feedback = state.completed.get("_acceptance_feedback")
        if acceptance_feedback:
            user_content += f"\n\n## Previous Acceptance Feedback\n{acceptance_feedback}"

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        content, _model = await self._call_llm_full(messages)
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            logger.warning("Critique-Acceptance returned non-JSON — defaulting to pass")
            return {"verdict": "pass"}
