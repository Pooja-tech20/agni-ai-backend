"""agent builder config

Revision ID: 3f9a1c2b7d10
Revises: b7c3e91d4a60
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "3f9a1c2b7d10"
down_revision = "b7c3e91d4a60"
branch_labels = None
depends_on = None

JSON_DEFAULTS = [
    ("functions", "[]"), ("calendars", "[]"), ("knowledge_base", "[]"),
    ("crm_sync", "{}"), ("speech_settings", "{}"), ("call_settings", "{}"),
    ("post_call_extraction", "{}"), ("webhook_settings", "{}"),
    ("prompt_variables", "{}"), ("agent_metadata", "{}"),
]


def upgrade() -> None:
    op.add_column("agents", sa.Column("system_prompt", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("welcome_message", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("llm_model", sa.String(100), nullable=True))
    op.add_column("agents", sa.Column("voice", sa.String(100), nullable=True))
    op.add_column("agents", sa.Column("memory_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("agents", sa.Column("emotion", sa.String(50), nullable=True))
    op.add_column("agents", sa.Column("accent", sa.String(50), nullable=True))
    op.add_column("agents", sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False))

    for col, default in JSON_DEFAULTS:
        op.add_column(
            "agents",
            sa.Column(
                col,
                postgresql.JSONB(),
                server_default=sa.text(f"'{default}'::jsonb"),
                nullable=False,
            ),
        )

    # Fails if existing agents already share a name within an org (case-insensitive);
    # rename those first.
    op.create_index(
        "uq_agents_client_lower_name", "agents",
        ["client_id", sa.text("lower(name)")], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_agents_client_lower_name", table_name="agents")
    for col in [
        "agent_metadata", "prompt_variables", "webhook_settings", "post_call_extraction",
        "call_settings", "speech_settings", "crm_sync", "knowledge_base", "calendars",
        "functions", "timezone", "accent", "emotion", "memory_enabled", "voice",
        "llm_model", "welcome_message", "system_prompt",
    ]:
        op.drop_column("agents", col)