# Phase 1.1 — Pipeline Fail-Closed — Design Spec

> **Date:** 2026-04-17
> **Status:** Draft — awaiting user approval
> **Approach:** Three coordinated fixes that flip the Quartet pipeline's safety-gate default from "pass" to "fail" whenever uncertainty arises. 3-4 day sprint.
> **Backlog refs:** AQ-001, AQ-003, AQ-004 (see `docs/audits/2026-04-16-phase0/agent-quality.md`, findings 1/3/4 at lines 23–52)

---

## Problem

The Phase 0 audit identified a systematic bias in the Quartet pipeline: whenever a critique, guardrail, or review stage hit uncertainty (malformed JSON, schema mismatch, medium-severity guardrail finding), the default path was "pass / approved / not-blocked." Three separate expressions of the same failure mode:

1. **Critique agents bypass the retry framework.** Both `CritiqueDirectionAgent` and `CritiqueAcceptanceAgent` make a single LLM call and fall back to "approved"/"pass" on any `JSONDecodeError` — with a single `logger.warning` that is invisible in production (`LOG_LEVEL=INFO`).
2. **Schema-validation exhaustion returns a best-effort dict.** The pipeline's shared `think_json` retries once with the schema appended on the second attempt; if that still fails, the executor reads the raw dict via permissive `.get()` defaults (`verdict → "pass"`, `blocked → False`). A Code Review that should be `reject` but couldn't match the schema ships as `pass`.
3. **Guardrail findings aren't actionable for the common case.** A prompt-injection or PII finding blocks the output but (a) the Task Agent is never re-invoked with redaction instructions, (b) the default `escalation_threshold=high` means medium-severity findings silently complete the task with the tainted content as the final deliverable, and (c) the raw tainted Task output is still surfaced in the completion message.

The combined observable behavior for a user: the weaker or more loaded the model, the *more permissive* the pipeline becomes — exactly backwards for a safety pipeline. Jeremy can see this in logs today (WARNING-only critique failures, guardrail-blocked tasks that still "complete" with a visible injection payload, code reviews that flip to `pass` after an LLM returns something the schema can't validate).

This sprint flips all three to fail-closed. Nothing else in the pipeline moves: no stage reorderings, no new agents, no model/prompt changes.

## Goals

1. **Critique failures are visible and conservative.** If a critique agent cannot produce valid JSON even with retry-with-feedback, the default verdict is `needs_revision` (Direction) or `fail` (Acceptance), and the event appears at ERROR level (not WARNING) so it surfaces in production logs.
2. **Schema-exhaustion becomes a real error.** When an LLM can't produce schema-compliant output after the retry, the agent run fails per the pod's configured `on_failure` policy — not a silent ship with all-permissive defaults.
3. **Guardrail findings drive remediation.** For remediable findings (prompt injection, PII exposure, credential leaks), the Task Agent is re-invoked with redaction instructions — the same loop shape that Code Review's `needs_refactor` already uses.
4. **Medium-severity findings no longer silently complete.** The default escalation threshold shifts from `high` to `medium`.
5. **Blocked tasks stop leaking tainted output.** When Guardrail blocks and the refactor loop exhausts max_retries, the final output the user sees is a safety-message summary, not the raw injected text.

## Non-Goals

- **AQ-002 (outcome-feedback positivity bias in memory).** Different subsystem — memory-service, not the pipeline. Separate sprint.
- **All other AQ-* findings** (P1 and below). Not this sprint.
- **Pipeline stage rewrites or stage-order changes.** The five stages stay as-is; the Decision Agent's firing condition (guardrail_blocked AND code_review_rejected) stays as-is — the new refactor loop handles most guardrail blocks before they escalate to Decision.
- **Per-finding-type escalation thresholds.** Considered and rejected: would require a new JSONB column, schema migration, pod-UI editor surface. The remediable finding types (injection/PII/credentials) are already handled by the refactor loop *before* the threshold check; the threshold now only governs non-remediable types (topic_drift, jailbreak attempts, scope creep), where a single scalar is correct.
- **Changes to CritiqueDirection's role** beyond AQ-001. See asymmetry note under Fix 3.
- **Changes to the Decision Agent's behavior.** Untouched.
- **Integration tests / live-service tests.** Unit tests only in this sprint — fast feedback loop, and every invariant can be tested by mocking the LLM call layer.

---

## The Three Fixes

Each fix below is scoped tight and can ship as its own commit. Ordered by dependency — AQ-001 and AQ-004 are independent; AQ-003 touches the most surface area and lands last.

### Fix 1 — AQ-001: Critique agents fail-closed on malformed JSON

**Defect.** Both critique agents call the LLM once via `_call_llm_full`, parse with a plain `json.loads`, and on `JSONDecodeError` return a pass-verdict dict:

- `CritiqueDirectionAgent` → `{"verdict": "approved"}` with `logger.warning`
- `CritiqueAcceptanceAgent` → `{"verdict": "pass"}` with `logger.warning`

Meanwhile every other pipeline agent (Context, Task, Guardrail, Code Review, Decision) uses `think_json(..., output_schema=<pydantic model>)`, which retries once with the bad output + a corrective user message before giving up. The critique agents opt out of this framework — so the weaker the model, the more likely the pipeline is to skip the safety gate entirely.

**Fix.** Route both critique agents through `think_json` with dedicated Pydantic output schemas. On retry exhaustion:

- Direction → `{"verdict": "needs_revision", "reason": "<automatic: LLM could not produce schema-valid output>"}`
- Acceptance → `{"verdict": "fail", "reason": "<automatic>"}`

Promote the log line from `logger.warning` to `logger.error` — this is a safety gate firing in failure mode, not a minor issue.

**Shape of change.** Two small agent files (`critique.py`), two new Pydantic schemas in `pipeline/schemas.py`. No changes to the executor — the existing `needs_revision` / `fail` handling branches already fire the loop-back or pause logic appropriately.

**Observable change.** When a small/weak model returns malformed JSON (or a cloud model under load truncates the response), the pipeline reports a critique failure, re-runs the Task Agent (Direction) or pauses for human review (Acceptance after exhausting revision rounds), and the event appears at ERROR level in the orchestrator logs. Previously: silent pass, invisible in production.

### Fix 2 — AQ-004: `think_json` schema-validation failure must raise, not return best-effort

**Defect.** After `think_json` runs its second attempt with the schema appended, if validation fails again, `_validate_schema` returns the raw parsed dict with a `logger.warning`. Downstream, the executor reads verdict/blocked/issues via permissive `.get()` defaults — `verdict → "pass"`, `blocked → False`, etc. So a Code Review result that should be `reject` but doesn't match the schema becomes `{}` → `.get("verdict", "pass")` → shipped. Same shape for Guardrail, Critique-Direction, Critique-Acceptance.

**Fix.** Modify `_validate_schema` so that after retry exhaustion, it raises `ValueError` instead of returning the raw dict. The outer `_run_agent` exception handler already applies the pod's configured `on_failure` policy (abort / skip / escalate). This matches how `think_json` already handles JSON-parse exhaustion (raises).

**Why this and not "fix permissive defaults everywhere."** The alternative — auditing every `.get(..., <default>)` in the executor and flipping each default to the conservative one — patches symptoms at every call site and drifts as new agents or fields get added. Raising at the validation layer fixes it structurally at the root: schema validation failure *is* an error, the failure policy already handles errors correctly, and the executor's permissive defaults become unreachable for the failure case.

**Shape of change.** One function modified in `base.py`. No other files touched for this fix — the executor's defaults stay as-is, but the code path that reached them in failure mode no longer runs.

**Observable change.** When an LLM produces output that can't be coerced to the schema even after retry with schema-appended feedback, the pipeline now fails the stage per the pod's `on_failure` policy. The Quartet pod default `on_failure="abort"` for Task Agent and `on_failure="escalate"` for Guardrail/CodeReview/Decision means the task either fails cleanly or pauses for human review — not ships an empty-dict "pass."

### Fix 3 — AQ-003: Guardrail findings become actionable

Three coordinated changes that share the goal of making a guardrail-blocked task either recover or surface as clearly blocked — never ship tainted content with a pass-looking status.

#### (a) Guardrail refactor loop

When Guardrail blocks with **remediable** finding types — prompt injection, PII exposure, credential leak — re-invoke the Task Agent with the findings translated into redaction instructions, then re-run the downstream stages. Mirrors the Code Review `needs_refactor` loop that already works today, capped by the same `max_retries` field on the pod's Guardrail agent row.

**Deliberate asymmetry from the Code Review loop.** The new guardrail-refactor loop re-runs **Task → Guardrail → Critique-Acceptance only** — it does *not* re-run Critique-Direction. The approach was already approved by Critique-Direction before the Guardrail block; the agent isn't doing the wrong thing, it just included flagged content. Re-running Critique-Direction wastes an LLM call for no safety benefit.

#### (b) Default escalation threshold: `high` → `medium`

After the refactor loop in (a) handles remediable finding types before escalation, the threshold only governs *non-remediable* types — topic drift, jailbreak attempts, scope creep. For those, `medium` is the correct conservative default: a medium-severity jailbreak attempt should pause for review, not silently complete.

The threshold stays a single scalar per pod (no per-finding-type dict). That's a deliberate decision — per-finding-type would need a new JSONB column and a larger migration, outside this sprint's scope. Post-refactor-loop, there's no longer a concrete failure mode the scalar can't cover.

#### (c) Suppress tainted output when finally blocked

Extract the inline final-output assembly currently at the bottom of the pipeline runner into a module-level helper `_build_final_output(state)`. When the guardrail refactor loop has exhausted `max_retries` without resolving, the final output is a safety-message string summarizing the findings — **not** the raw Task output. The current behavior ("task_complete with tainted content in the preview") is the worst of both worlds.

**Observable change.** A task with a prompt-injected document that could previously complete with the injection payload visible in the final message now:

1. Gets re-run up to `max_retries` with the findings translated to redaction instructions.
2. If still blocked, surfaces "This task was blocked by Nova's safety checks: <finding summaries>" as the final output. The tainted text is never shown to the user.
3. Pauses for human review at medium finding severity, not only at high.

#### Shape of change

| Area | File | Change |
|---|---|---|
| Counter | `orchestrator/app/pipeline/executor.py` (counter block near line 296–302) | Add `guardrail_refactor_iterations = 0`, mirroring `code_review_refactor_iterations` |
| Serial guardrail block | `orchestrator/app/pipeline/executor.py` (lines 448–450) | Replace the single `flags.add("guardrail_blocked")` line with the full refactor-loop block (mirrors CR loop at lines 452–484) |
| Parallel-group guardrail block | `orchestrator/app/pipeline/executor.py` (lines 358–367) | Same expansion for the parallel-group code path |
| Rerun hint | `orchestrator/app/pipeline/executor.py:1496–1500` (`_needs_rerun`) | Extend to recognize the guardrail-refactor feedback key so checkpoints clear and Task re-runs |
| Pause gate | `orchestrator/app/pipeline/executor.py:1521` (`_should_pause_for_review`) | No code change — but the default pod `escalation_threshold` fed into this function changes at the DB layer |
| Final-output assembly | `orchestrator/app/pipeline/executor.py:550–571` | Extract into module-level `_build_final_output(state) -> str`; new branch returns safety-message string when `guardrail_blocked` is still set after loop exhaustion |
| Feedback formatter | `orchestrator/app/pipeline/executor.py` (new helper) | Module-level `_build_guardrail_refactor_feedback(findings) -> str` returns the redaction-instructions prompt prefix |
| Migration | `orchestrator/app/migrations/002_phase4_schema.sql:19` (column default) and `:254` (seed rows) | Idempotent `ALTER TABLE pods ALTER COLUMN escalation_threshold SET DEFAULT 'medium'` + `UPDATE pods SET escalation_threshold = 'medium' WHERE escalation_threshold = 'high' AND is_system_default` (conservative — only migrates rows still on the system default). See "Rollback" for the revert path. |
| Router default | `orchestrator/app/pipeline_router.py:81` | Change `PodRequest.escalation_threshold: str = "high"` to `"medium"` |

The feedback-formatter is module-level (not nested inside `run_pipeline`) so unit tests can import and call it directly — same shape as the existing `_needs_rerun` and `_should_pause_for_review` helpers.

---

## Order of Operations

1. **AQ-001 first.** Smallest surface, zero shared-state risk, locks the easiest fail-closed invariant. Two critique files + two schema entries.
2. **AQ-004 second.** One function in `base.py`. Independent of AQ-001. Lands the "schema exhaustion is an error" rule before AQ-003 leans on it.
3. **AQ-003 last.** Most surface area, touches the executor + a migration + the pod-router default. Landing last means the first two invariants are already in place and the refactor-loop tests can rely on them.

Each fix is a separate commit, independently revertable.

## Success Criteria

Phase 1.1 is complete when all of the following are true:

1. **AQ-001** — With `LOG_LEVEL=INFO`, a forced malformed-JSON response from either critique agent surfaces at ERROR level in `docker compose logs orchestrator`, and the task either loops back to the Task Agent (Direction → `needs_revision`) or pauses for human review (Acceptance → `fail` after max revisions).
2. **AQ-004** — A forced schema-validation failure (e.g. missing required field) on any agent using `think_json` causes the pipeline stage to fail per the pod's `on_failure` policy, not silently produce an all-defaults dict.
3. **AQ-003 refactor loop** — A Task output containing a prompt-injection marker is re-run by the Task Agent with redaction instructions and passes Guardrail on retry. Verified by a unit test mocking Guardrail to block once and then pass.
4. **AQ-003 escalation threshold** — A fresh pod row has `escalation_threshold='medium'`. Existing pods still on the old default (`high`, `is_system_default=true`) are migrated to `medium`. Pods that have been customized by the user are not migrated.
5. **AQ-003 tainted-output suppression** — When Guardrail blocks after max retries, the task's final output is a safety-message string containing the finding summaries, not the raw Task output. No injection payload visible in the completion message.
6. All eight new unit tests pass under `cd orchestrator && uv run pytest tests/test_critique_fail_closed.py tests/test_schema_fail_closed.py tests/test_guardrail_refactor.py -v`.
7. `BACKLOG.md` rows AQ-001, AQ-003, AQ-004 flip from `Open` to `Done`.

## Testing Discipline

Pure-Python unit tests in `orchestrator/tests/`, mocked at the `_call_llm_full` level (or the `_run_agent` boundary for executor-level assertions). No integration tests, no live LLM, no database, no Docker. Follows the existing pattern of `orchestrator/tests/test_runner.py` and `test_reaper.py`.

| Fix | Test focus | Rationale |
|---|---|---|
| AQ-001 | Two tests: Direction and Acceptance each fail-closed on malformed JSON twice; log emitted at ERROR level | Locks the invariant; cheap to write |
| AQ-004 | Two tests: `_validate_schema` raises on double-failure; executor applies pod's `on_failure` when `_run_agent` raises | Both sides of the contract tested |
| AQ-003 | Four tests: feedback-formatter shape, refactor-loop triggers and completes clean, safety-message output on exhaustion, medium-severity pause fires | Largest surface, most tests |

**Explicit out-of-test-scope.** No test of the SQL migration itself (idempotent `ALTER` is self-verifying; migration pattern already tested in Phase 1.0). No test of the router default change (Pydantic default; reading the constant proves the fix).

---

## Risks & Rollback

- **AQ-001 false negatives.** If a real-world production model produces JSON that think_json can't validate but the pipeline's previous fail-open behavior was load-bearing for some user's workflow, tasks that previously "worked" will now fail or loop. Mitigation: the retry-with-schema pattern is exactly what every other agent uses; any model good enough to pass the rest of the pipeline is good enough to pass critique schema validation. Revert: `git revert <sha>` restores fail-open.
- **AQ-004 could surface latent bad agents.** If any pod has a misconfigured `on_failure="abort"` on a historically-broken agent, this change will start failing tasks that previously silently "completed" with `{}`. That's the correct behavior, but may produce a burst of failed tasks immediately after deploy. Mitigation: Nova's failed-task audit log shows what's failing; investigate and adjust the pod config rather than reverting. Revert: `git revert <sha>` restores the best-effort-dict path.
- **AQ-003 refactor loop could mask a real security issue.** If the Task Agent is told to redact a credential and complies on the retry, the guardrail-blocked event is resolved and the original finding disappears. Mitigation: every refactor iteration is audited (`state.completed["_guardrail_refactor_feedback"]` + existing audit log writes) so the original finding is preserved. Revert: `git revert <sha>` restores the current "block + escalate or silently complete" behavior.
- **AQ-003 migration breaks existing pods.** The `UPDATE pods SET escalation_threshold = 'medium'` is gated by `is_system_default = true`, so user-customized pods are untouched. Rollback for the migration is a manual `ALTER TABLE pods ALTER COLUMN escalation_threshold SET DEFAULT 'high'; UPDATE pods SET escalation_threshold = 'high' WHERE is_system_default AND escalation_threshold = 'medium';` — idempotent, matches the forward-migration shape.
- **AQ-003 safety-message output changes user-facing UX.** A user expecting the full Task output now sees a terse safety summary when the pipeline blocks. That's the correct behavior per the design, but it is a user-visible change. No mitigation needed; documented in the success criteria.

## Definition of Done

- Three commits on `main`, each for one fix, each following the repo's conventional-commit style (`fix(critique): …`, `fix(pipeline): …`, `feat(guardrail): …`).
- Eight new unit tests pass in `orchestrator/tests/`.
- All five success criteria verified manually (log-level check, schema-exhaustion smoke, refactor-loop smoke, fresh-pod check, suppressed-output check).
- `BACKLOG.md` rows AQ-001, AQ-003, AQ-004 updated to `Done` with commit SHAs.

## Out-of-Scope Follow-ups

- **AQ-002** (outcome-feedback positivity bias) — memory-service, separate sprint.
- Per-finding-type escalation thresholds — requires JSONB column + pod-UI redesign; file as a follow-up if users report the scalar is too coarse.
- Critique-Direction pruning — the agent's prompt could be tightened to be more assertive about "needs_revision" verdicts even on schema-valid output; out of this sprint.
- Router surface for `needs_clarification` verdict — the `CritiqueDirectionAgent` still supports `needs_clarification` (currently handled by `_pause_for_clarification`); unchanged here but could be reviewed in a later UX pass.
