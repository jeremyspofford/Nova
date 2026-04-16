"""add pending_tool_call to conversations

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import JSON

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("pending_tool_call", JSON(), nullable=True))
    op.add_column("conversations", sa.Column("pending_tool_call_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "pending_tool_call_at")
    op.drop_column("conversations", "pending_tool_call")
