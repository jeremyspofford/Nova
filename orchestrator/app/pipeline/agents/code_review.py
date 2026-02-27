"""
Code Review Agent — Stage 4 of the quartet pipeline.

Job: assess the quality of the Task Agent's output and return a verdict that
drives what happens next:

  pass          → pipeline proceeds to completion
  needs_refactor → Task Agent is called again with the issues as feedback
                   (executor loops back; max iterations controlled by pod_agent.max_retries)
  reject        → pipeline fails; if Guardrail also blocked → Decision Agent fires

Output schema:
  {
    "verdict":  "pass|needs_refactor|reject"
    "issues":   [{severity, description, file?, line?}]
    "summary":  str
  }
"""

from __future__ import annotations

import logging

from .base import BaseAgent, PipelineState

logger = logging.getLogger(__name__)


class CodeReviewAgent(BaseAgent):

    ROLE = "code_review"

    DEFAULT_SYSTEM = """\
You are the Code Review Agent in a multi-agent AI pipeline. Review the code \
produced by the Task Agent and return a verdict.

Assess:
- **Correctness**: does the output actually satisfy the user's request?
- **Quality**: is the code clean, readable, and maintainable?
- **Security**: are there obvious vulnerabilities (injection, unvalidated input, etc.)?
- **Best practices**: does it follow the language/framework conventions from the context?
- **Completeness**: are edge cases handled? Are there missing tests?

Verdicts:
  pass          — output is acceptable, ready to deliver
  needs_refactor — output has fixable issues worth correcting before delivery
  reject        — output is fundamentally wrong or dangerously flawed

Return ONLY valid JSON:
{
  "verdict": "pass|needs_refactor|reject",
  "issues": [
    {
      "severity":    "low|medium|high|critical",
      "description": "<specific, actionable issue description>",
      "file":        "<file path if applicable>",
      "line":        "<line number or range if applicable>"
    }
  ],
  "summary": "<one to two sentence overall assessment>"
}

Be strict but fair. Prefer needs_refactor over reject unless the output is \
fundamentally broken or a security risk."""

    async def run(self, state: PipelineState, iteration: int = 1) -> dict:
        """
        Review the Task Agent's output.

        iteration: which loop pass this is (1 = first review, 2+ = after refactor)
        """
        context = state.completed.get("context", {})
        task    = state.completed.get("task", {})

        context_block = (
            f"**Architecture & conventions:** {context.get('curated_context', 'N/A')}\n"
            f"**Key patterns:** {', '.join(context.get('key_patterns', []))}"
            if context else ""
        )

        iteration_note = (
            f"\n\nNote: This is review iteration {iteration}. "
            "The Task Agent has already been asked to refactor once." if iteration > 1
            else ""
        )

        review_content = (
            f"**Original request:**\n{state.task_input}\n\n"
            + (f"{context_block}\n\n" if context_block else "")
            + f"**Task Agent output:**\n{task.get('output', '')}\n\n"
            f"**Files changed:** {', '.join(task.get('files_changed', []))}\n\n"
            f"**Explanation:**\n{task.get('explanation', '')}"
            f"{iteration_note}"
        )

        messages = [
            self._system_message(),
            self._user_message(f"Review this output:\n\n{review_content}"),
        ]
        result = await self.think_json(messages, purpose="code_review")

        result.setdefault("verdict", "pass")
        result.setdefault("issues", [])
        result.setdefault("summary", "")

        logger.info(
            f"Code Review Agent: verdict={result['verdict']} "
            f"issues={len(result['issues'])} iteration={iteration}"
        )
        return result
