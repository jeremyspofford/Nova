"""
Context Agent — Stage 1 of the quartet pipeline.

Job: curate relevant context from the workspace before the Task Agent runs.
This prevents the Task Agent's context window from being polluted by irrelevant
files. The Task Agent receives a clean, focused context package instead of
the entire codebase.

Output schema:
  {
    "curated_context":  str   — summary of architecture, conventions, relevant patterns
    "relevant_files":   list  — most relevant file paths the Task Agent should read
    "key_patterns":     list  — important conventions/patterns found (naming, structure)
    "recommendations":  str   — brief guidance for the Task Agent
  }
"""

from __future__ import annotations

import logging

from .base import BaseAgent, PipelineState

logger = logging.getLogger(__name__)


class ContextAgent(BaseAgent):

    ROLE = "context"

    DEFAULT_SYSTEM = """\
You are the Context Agent in a multi-agent AI pipeline. Your sole job is to \
curate relevant context from the codebase BEFORE the Task Agent runs.

You have access to workspace tools. Use them to:
1. List the project structure to understand what exists
2. Search for files and patterns relevant to the user's request
3. Read the most relevant files to understand current implementation and conventions
4. Synthesise your findings into a concise context package

Return ONLY valid JSON matching this exact schema — no markdown, no preamble:
{
  "curated_context":  "<summary of relevant architecture, patterns, conventions>",
  "relevant_files":   ["<file_path>", ...],
  "key_patterns":     ["<pattern or convention>", ...],
  "recommendations":  "<brief guidance for the Task Agent>"
}"""

    async def run(self, state: PipelineState) -> dict:
        """
        Explore the workspace and build a context package for the Task Agent.
        Uses tool calls to list/read/search the codebase before summarising.
        """
        # Context Agent uses the full agent runner (tool-use loop) to explore
        # the workspace, then distils its findings into a JSON context package.
        # We call the runner as a sub-invocation rather than re-implementing
        # the tool loop here.
        from ...agents.runner import run_agent_turn_raw
        from ...tools import get_all_tools

        # Filter to read-only operations — context agent must never write files.
        # Also allow any MCP tool (mcp__* prefix) so registered MCP servers
        # (search, browse, read) are available for context gathering.
        READ_ONLY = {"list_dir", "read_file", "search_codebase", "git_status", "git_log"}
        tools = [t for t in get_all_tools() if t.name in READ_ONLY or t.name.startswith("mcp__")]

        prompt = (
            f"The Task Agent needs to complete the following request:\n\n"
            f"{state.task_input}\n\n"
            "Explore the workspace and build a context package. "
            "Use list_dir, read_file, and search_codebase to understand the relevant "
            "parts of the codebase. Then return your structured JSON context package."
        )

        raw_output, in_tokens, out_tokens, cost_usd = await run_agent_turn_raw(
            system_prompt=self.system_prompt,
            user_message=prompt,
            model=self.model,
            tools=tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            return_usage=True,
        )
        # Accumulate tool-loop usage into agent usage
        self._usage["input_tokens"] += in_tokens
        self._usage["output_tokens"] += out_tokens
        self._usage["cost_usd"] += cost_usd or 0.0

        # The runner returns the final assistant message. Parse it as JSON.
        messages = [
            self._system_message(),
            self._user_message(prompt),
            {"role": "assistant", "content": raw_output},
            self._user_message(
                "Now return your structured JSON context package as described in your instructions."
            ),
        ]
        return await self.think_json(messages, purpose="context_package")
