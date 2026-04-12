"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import JSON

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("goal", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="inbox"),
        sa.Column("origin_event_id", sa.String(), nullable=True),
        sa.Column("board_column_id", sa.String(), nullable=True),
        sa.Column("owner_type", sa.String(), nullable=True),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.String(), nullable=False, server_default="normal"),
        sa.Column("risk_class", sa.String(), nullable=False, server_default="low"),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_decision", sa.String(), nullable=False, server_default="none"),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_summary", sa.String(), nullable=True),
        sa.Column("labels", JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata", JSON(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("payload", JSON(), nullable=False, server_default="{}"),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("priority", sa.String(), nullable=False, server_default="normal"),
        sa.Column("risk_class", sa.String(), nullable=False, server_default="low"),
        sa.Column("actor_type", sa.String(), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("entity_refs", JSON(), nullable=False, server_default="[]"),
        sa.Column("task_ref", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("tool_name", sa.String(), nullable=True),
        sa.Column("workflow_ref", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input", JSON(), nullable=True),
        sa.Column("output", JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("executor_type", sa.String(), nullable=False, server_default="system"),
        sa.Column("executor_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("consequence", sa.String(), nullable=True),
        sa.Column("options", JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "board_columns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("status_filter", JSON(), nullable=True),
        sa.Column("work_in_progress_limit", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "entities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("state", JSON(), nullable=False, server_default="{}"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSON(), nullable=True),
        sa.Column("capabilities", JSON(), nullable=False, server_default="[]"),
        sa.Column("room_or_group", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tools",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("adapter_type", sa.String(), nullable=False),
        sa.Column("input_schema", JSON(), nullable=False, server_default="{}"),
        sa.Column("output_schema", JSON(), nullable=True),
        sa.Column("risk_class", sa.String(), nullable=False, server_default="low"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("tags", JSON(), nullable=False, server_default="[]"),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "llm_provider_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("endpoint_ref", sa.String(), nullable=False),
        sa.Column("model_ref", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("privacy_class", sa.String(), nullable=False, server_default="local_only"),
        sa.Column("cost_class", sa.String(), nullable=False, server_default="low"),
        sa.Column("latency_class", sa.String(), nullable=False, server_default="medium"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("llm_provider_profiles")
    op.drop_table("tools")
    op.drop_table("entities")
    op.drop_table("board_columns")
    op.drop_table("approvals")
    op.drop_table("runs")
    op.drop_table("events")
    op.drop_table("tasks")
