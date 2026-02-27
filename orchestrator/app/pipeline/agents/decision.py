"""
Decision Agent — Conditional stage (fires only when Guardrail + Code Review both fail).

Job: when the Guardrail blocks AND Code Review rejects, a human could just get
an error message — but that wastes the work done so far. The Decision Agent instead:
  1. Reviews both sets of findings
  2. Determines whether a human override can safely proceed, or must escalate
  3. Produces an Architecture Decision Record (ADR) artifact documenting the decision

run_condition in DB: {"type":"and","conditions":[
  {"type":"on_flag","flag":"guardrail_blocked"},
  {"type":"on_flag","flag":"code_review_rejected"}
]}

Output schema:
  {
    "action":             "escalate|override"
    "reasoning":          str   — justification for the decision
    "adr":                str   — full ADR in markdown
    "escalation_message": str   — message shown to human reviewer (if escalate)
  }
"""

from __future__ import annotations

import logging

from .base import BaseAgent, PipelineState

logger = logging.getLogger(__name__)


class DecisionAgent(BaseAgent):

    ROLE = "decision"

    DEFAULT_SYSTEM = """\
You are the Decision Agent in a multi-agent AI pipeline. You are called only \
when BOTH the Guardrail Agent blocked the output AND the Code Review Agent \
rejected it.

Your job:
1. Review the original request, task output, guardrail findings, and code review issues
2. Determine if this situation should be ESCALATED to a human reviewer, or if the \
   concerns can be OVERRIDDEN with documented justification
3. Produce an Architecture Decision Record (ADR) documenting this decision

Override only if: the findings are demonstrably false positives AND the code \
quality issues are minor or already addressed.

Escalate if: any guardrail finding is high/critical severity, or code review \
found a fundamental flaw.

Return ONLY valid JSON:
{
  "action": "escalate|override",
  "reasoning": "<why you chose this action>",
  "adr": "<full Architecture Decision Record in markdown — include context, decision, consequences>",
  "escalation_message": "<message for the human reviewer describing what needs their decision>"
}"""

    async def run(self, state: PipelineState) -> dict:
        task     = state.completed.get("task",        {})
        guardrail = state.completed.get("guardrail",  {})
        review    = state.completed.get("code_review", {})

        content = (
            f"**Original request:**\n{state.task_input}\n\n"
            f"**Task Agent output summary:**\n{task.get('output', 'N/A')}\n\n"
            f"**Guardrail findings:**\n"
            + "\n".join(
                f"- [{f['severity'].upper()}] {f['type']}: {f['description']}"
                for f in guardrail.get("findings", [])
            )
            + f"\n\n**Code Review verdict:** {review.get('verdict', 'unknown')}\n"
            "**Code Review issues:**\n"
            + "\n".join(
                f"- [{i['severity'].upper()}] {i['description']}"
                for i in review.get("issues", [])
            )
        )

        messages = [
            self._system_message(),
            self._user_message(f"Review this conflicted pipeline result:\n\n{content}"),
        ]
        result = await self.think_json(messages, purpose="decision")

        result.setdefault("action", "escalate")
        result.setdefault("reasoning", "")
        result.setdefault("adr", "")
        result.setdefault("escalation_message", "Requires human review.")

        logger.info(f"Decision Agent: action={result['action']}")
        return result
