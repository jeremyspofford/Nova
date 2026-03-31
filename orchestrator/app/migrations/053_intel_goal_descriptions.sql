-- Migration 053: Update intel system goal descriptions with concrete tool instructions
-- The original descriptions were too vague for Cortex agents to execute effectively.
-- These updated descriptions reference specific tools and define success criteria.

UPDATE goals SET description =
'Sweep all intel feed content from the past 24 hours and build knowledge.

Steps:
1. Call query_intel_content(since_hours=24) to get recent feed items.
2. For each batch of items, call search_memory(query=<item title>) to check what you already know.
3. Identify items that add genuinely new information vs duplicates of existing knowledge.
4. Summarize key findings — new model releases, API changes, security advisories, research breakthroughs.
5. If any item is urgent (security vulnerability, breaking API change, critical release), flag it in your summary.

Success criteria: You have reviewed all recent items and can state what is new vs already known.
Do NOT create recommendations during daily sweeps — that is the weekly synthesis goal.'
WHERE id = 'd0000000-0000-0000-0000-000000000001';

UPDATE goals SET description =
'Analyze the past week of intel content, cross-reference with memory, and generate graded recommendations.

Steps:
1. Call query_intel_content(since_hours=168) to get the full week of feed content.
2. Call get_dismissed_hashes() to retrieve previously rejected recommendation hashes — avoid re-recommending similar content.
3. Call what_do_i_know() to understand your current knowledge landscape.
4. Group content into themes (new models, API changes, tooling updates, research, security).
5. For each theme with actionable insights, call create_recommendation() with:
   - grade: A (act now), B (worth investigating), C (informational)
   - confidence: 0.0-1.0 based on source reliability and corroboration
   - source_content_ids: link the content items that informed the recommendation
   - rationale: explain WHY this matters to Nova and the user
6. Re-evaluate any deferred recommendations — call query_intel_content to check for new evidence.

Grading guide:
- Grade A: Direct impact on Nova capabilities, security, or user workflow. Multiple corroborating sources.
- Grade B: Interesting development worth tracking. Single reliable source or emerging pattern.
- Grade C: Background context. No immediate action but enriches knowledge.

Success criteria: At least one recommendation created if the week had substantive content. Zero recommendations is acceptable only if nothing noteworthy happened.'
WHERE id = 'd0000000-0000-0000-0000-000000000002';

UPDATE goals SET description =
'Compare Nova''s current capabilities against accumulated intelligence. Identify gaps and suggest improvements.

Steps:
1. Call get_memory_stats() to understand the current state of the engram network.
2. Call query_intel_content(since_hours=336, category=<each category>) to survey recent trends.
3. Call search_memory(query="capability gaps") and search_memory(query="improvement suggestions") to review past self-assessments.
4. Compare what the AI ecosystem is doing (from intel) against what Nova can do (from memory and platform config).
5. Identify concrete gaps: models Nova should support, tools it should integrate, patterns it should adopt.
6. For each actionable gap, call create_recommendation() with grade B or A and category "self-improvement".

Success criteria: You have compared at least 3 intel categories against Nova capabilities and documented findings. Create recommendations only for gaps that are practically addressable.'
WHERE id = 'd0000000-0000-0000-0000-000000000003';
