"""Tier and task-type enums for adaptive model routing.

Named RoutingTaskType (not TaskType) to avoid collision with
nova_contracts.orchestrator.TaskType which is a different enum.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

Tier = Literal["best", "mid", "cheap"]
TIER_ORDER: list[str] = ["best", "mid", "cheap"]


class RoutingTaskType(str, Enum):
    """Task types for model routing and outcome tracking."""
    planning = "planning"
    task_execution = "task_execution"
    goal_work = "goal_work"
    code_review = "code_review"
    guardrail = "guardrail"
    context_retrieval = "context_retrieval"
    decision = "decision"
    reflection = "reflection"
    narration = "narration"
    extraction = "extraction"
    chat = "chat"
