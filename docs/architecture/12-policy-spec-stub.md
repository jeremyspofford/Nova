# 12 – Policy Specification (MVP Stub)

## MVP approach

For MVP, policy is embedded in:

- `Tool.risk_class` and `requires_approval` fields (defined in 07-workflow-spec.md)
- Nova-lite checks these before invoking tools (05-nova-lite-spec.md)
- Nova Board surfaces approvals for `risk_class=high` tools (06-nova-board-spec.md)

## v2 expansion

Future policy service will support:
- dynamic risk assessment based on context (time, user presence, task history)
- escalation rules (e.g., notify via multiple channels)
- approval workflows beyond simple approve/deny

MVP workflows use tool metadata as the policy signal.
