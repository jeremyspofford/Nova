"""
Pydantic schemas for pipeline agent outputs.

Each pipeline stage has a defined output schema. When passed to think_json(),
the schema validates the LLM's JSON output and coerces minor issues (missing
defaults, wrong types that are safely convertible). On hard validation failure,
think_json retries the LLM with the schema definition appended to the prompt.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Context Agent (Stage 1) ──────────────────────────────────────────────────

class ContextAgentOutput(BaseModel):
    curated_context: str = Field(description="Summary of architecture, conventions, relevant patterns")
    relevant_files: list[str] = Field(default_factory=list)
    key_patterns: list[str] = Field(default_factory=list)
    recommendations: str = Field(default="")


# ── Task Agent (Stage 2) ─────────────────────────────────────────────────────

class TaskAgentOutput(BaseModel):
    output: str = Field(description="Summary of what was accomplished")
    files_changed: list[str] = Field(default_factory=list)
    explanation: str = Field(default="")
    commands_run: list[str] = Field(default_factory=list)


# ── Guardrail Agent (Stage 3) ────────────────────────────────────────────────

class GuardrailFinding(BaseModel):
    type: str
    severity: str
    description: str
    evidence: str = ""


class GuardrailOutput(BaseModel):
    blocked: bool = False
    tier: int = 1
    findings: list[GuardrailFinding] = Field(default_factory=list)
    summary: str = Field(default="")


# ── Code Review Agent (Stage 4) ──────────────────────────────────────────────

class CodeReviewVerdict(str, Enum):
    PASS = "pass"
    NEEDS_REFACTOR = "needs_refactor"
    REJECT = "reject"


class CodeReviewIssue(BaseModel):
    severity: str
    description: str
    file: str = ""
    line: str = ""
    suggestion: str = ""


class CodeReviewOutput(BaseModel):
    verdict: str = Field(default="pass", description="pass, needs_refactor, or reject")
    issues: list[CodeReviewIssue] = Field(default_factory=list)
    summary: str = Field(default="")


# ── Decision Agent (Conditional) ─────────────────────────────────────────────

class DecisionOutput(BaseModel):
    action: str = Field(default="escalate", description="escalate or override")
    reasoning: str = Field(default="")
    adr: str = Field(default="", description="Architecture Decision Record in markdown")
    escalation_message: str = Field(default="Requires human review.")


# ── Critique-Direction (approval gate) ───────────────────────────────────────

class CritiqueDirectionOutput(BaseModel):
    verdict: str = Field(
        default="needs_revision",
        description="approved | needs_revision | needs_clarification",
    )
    feedback: str = Field(default="")
    questions: list[str] = Field(default_factory=list)
    reason: str = Field(default="")


# ── Critique-Acceptance (final gate) ─────────────────────────────────────────

class CritiqueAcceptanceOutput(BaseModel):
    verdict: str = Field(default="fail", description="pass | fail")
    feedback: str = Field(default="")
    reason: str = Field(default="")
