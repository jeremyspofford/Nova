"""Pure-function aggregator: (cmd_results, quartet_review, criteria_eval) → outcome.

Outcomes: 'pass', 'fail', 'human-review'.
"""
from __future__ import annotations


def aggregate(cmd_results: list[dict], quartet_review: dict | None, criteria_eval: list[dict]) -> str:
    """Combine signals into a single outcome.

    Rules:
      - All cmds exit 0, quartet ≥ 0.7, criteria ≥ 75% pass → pass
      - Any cmd non-zero AND quartet ≥ 0.7 (LLM agrees it failed) → fail
      - Any cmd non-zero AND quartet < 0.7 (LLM uncertain) → human-review
      - All cmds pass AND criteria majority pass AND quartet < 0.5 → human-review
      - 0 commands AND only LLM signals: pass if quartet ≥ 0.85 else human-review
      - Criteria majority FAIL blocks pass even if commands+quartet green → fail
    """
    quartet_conf = float((quartet_review or {}).get("confidence") or 0.0)
    cmd_pass = all(int(c.get("exit_code") or 0) == 0 for c in cmd_results)
    criteria_pass_ratio = (
        sum(1 for x in criteria_eval if x.get("pass")) / len(criteria_eval)
        if criteria_eval else 1.0
    )

    if not cmd_results and not criteria_eval:
        # Degenerate: no signals at all — escalate
        return "human-review"

    # No commands: rely on quartet + criteria
    if not cmd_results:
        if quartet_conf >= 0.85 and criteria_pass_ratio >= 0.75:
            return "pass"
        return "human-review"

    # Have commands
    if not cmd_pass:
        return "fail" if quartet_conf >= 0.7 else "human-review"

    # All commands green
    if criteria_pass_ratio < 0.5:
        return "fail"  # criteria majority fail blocks pass
    if quartet_conf < 0.5:
        return "human-review"  # quartet disagrees with green tests
    if quartet_conf >= 0.7 and criteria_pass_ratio >= 0.75:
        return "pass"
    return "human-review"
