"""replace interval_seconds with cron_expression

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheduled_triggers", sa.Column("cron_expression", sa.String(), nullable=True))

    # Backfill cron_expression for the two seeded triggers.
    op.execute(
        "UPDATE scheduled_triggers SET cron_expression = '*/30 * * * *' WHERE id = 'system-heartbeat'"
    )
    op.execute(
        "UPDATE scheduled_triggers SET cron_expression = '0 0 * * *' WHERE id = 'daily-summary'"
    )

    # Rewrite the two seeded triggers' payload_template to the new {tool, input} shape.
    # seed_scheduled_triggers preserves existing payload_template on restart (user data is
    # sacred), so without this data migration the stale {"check": "system_health"} payload
    # would persist and bypass the triage scheduler-source branch's tool-routing.
    op.execute(
        "UPDATE scheduled_triggers SET payload_template = '{\"tool\": \"nova.system_health\", \"input\": {}}'::json "
        "WHERE id = 'system-heartbeat'"
    )
    op.execute(
        "UPDATE scheduled_triggers SET payload_template = '{\"tool\": \"nova.daily_summary\", \"input\": {\"window_hours\": 24}}'::json "
        "WHERE id = 'daily-summary'"
    )

    op.alter_column("scheduled_triggers", "cron_expression", nullable=False)
    op.drop_column("scheduled_triggers", "interval_seconds")


def downgrade() -> None:
    op.add_column("scheduled_triggers", sa.Column("interval_seconds", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE scheduled_triggers SET interval_seconds = 1800 WHERE id = 'system-heartbeat'"
    )
    op.execute(
        "UPDATE scheduled_triggers SET interval_seconds = 86400 WHERE id = 'daily-summary'"
    )
    # Restore the old payload shape for the two seeded triggers.
    op.execute(
        "UPDATE scheduled_triggers SET payload_template = '{\"check\": \"system_health\"}'::json "
        "WHERE id = 'system-heartbeat'"
    )
    op.execute(
        "UPDATE scheduled_triggers SET payload_template = '{\"check\": \"daily_summary\"}'::json "
        "WHERE id = 'daily-summary'"
    )
    op.alter_column("scheduled_triggers", "interval_seconds", nullable=False)
    op.drop_column("scheduled_triggers", "cron_expression")
