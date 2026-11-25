"""platform: org controls, credit ledger, api keys, webhooks, campaign contacts, notes, integrations, audit

Revision ID: 9a1b2c3d4e5f
Revises: f2a7c9d1e4b6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a1b2c3d4e5f"
down_revision: Union[str, None] = "f2a7c9d1e4b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _base_cols():
    return [
        sa.Column("id", UUID, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # ---- clients: platform controls + org-level credits ----
    op.add_column("clients", sa.Column("status", sa.String(20), nullable=False, server_default="active"))
    op.add_column("clients", sa.Column("suspended_reason", sa.String(255), nullable=True))
    op.add_column("clients", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("plan", sa.String(50), nullable=False, server_default="free"))
    op.add_column("clients", sa.Column("credit_balance", sa.Numeric(14, 3), nullable=False, server_default="10"))
    op.add_column("clients", sa.Column("credits_per_minute", sa.Numeric(10, 4), nullable=True))
    op.add_column("clients", sa.Column("max_concurrent_calls", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("clients", sa.Column("max_agents", sa.Integer(), nullable=True))
    op.add_column("clients", sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    # Carry existing per-user balances over to the organization.
    op.execute(
        "UPDATE clients SET credit_balance = COALESCE("
        "(SELECT SUM(u.credits) FROM users u WHERE u.client_id = clients.id), 10)"
    )

    op.create_table(
        "credit_transactions",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 3), nullable=False),
        sa.Column("balance_after", sa.Numeric(14, 3), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("call_id", UUID, sa.ForeignKey("calls.id", ondelete="SET NULL")),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reference", sa.String(120)),
    )
    op.create_index("ix_credit_tx_client_created", "credit_transactions", ["client_id", "created_at"])
    op.create_index(
        "uq_credit_tx_usage_call", "credit_transactions", ["call_id"],
        unique=True, postgresql_where=sa.text("type = 'usage'"),
    )

    op.create_table(
        "api_keys",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_api_keys_client_id", "api_keys", ["client_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "webhook_endpoints",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("secret", sa.String(80), nullable=False),
        sa.Column("events", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_webhook_endpoints_client_id", "webhook_endpoints", ["client_id"])

    op.create_table(
        "webhook_deliveries",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint_id", UUID, sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.String(60), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_status_code", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_webhook_deliveries_client_id", "webhook_deliveries", ["client_id"])
    op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_webhook_deliveries_due", "webhook_deliveries", ["status", "next_attempt_at"])

    op.create_table(
        "campaign_contacts",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", UUID, sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", UUID, sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_call_id", UUID, sa.ForeignKey("calls.id", ondelete="SET NULL")),
        sa.UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_contact"),
    )
    op.create_index("ix_campaign_contacts_due", "campaign_contacts", ["campaign_id", "status", "next_attempt_at"])

    op.create_table(
        "contact_notes",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", UUID, sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("body", sa.Text(), nullable=False),
    )
    op.create_index("ix_contact_notes_contact_id", "contact_notes", ["contact_id"])

    op.create_table(
        "integration_accounts",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("label", sa.String(120)),
        sa.Column("credential_encrypted", sa.Text(), nullable=False),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.create_index("ix_integration_accounts_client_id", "integration_accounts", ["client_id"])

    op.create_table(
        "appointments",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_booking_id", sa.String(120)),
        sa.Column("agent_id", UUID, sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("call_id", UUID, sa.ForeignKey("calls.id", ondelete="SET NULL")),
        sa.Column("contact_id", UUID, sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("attendee_name", sa.String(255)),
        sa.Column("attendee_email", sa.String(255)),
        sa.Column("attendee_phone", sa.String(50)),
        sa.Column("title", sa.String(255)),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="booked"),
        sa.Column("raw", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_appointments_client_start", "appointments", ["client_id", "start_time"])

    op.create_table(
        "audit_logs",
        *_base_cols(),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="SET NULL")),
        sa.Column("actor_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(60)),
        sa.Column("target_id", sa.String(80)),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_audit_logs_client_created", "audit_logs", ["client_id", "created_at"])

    # Helpful indexes for dashboards / dialer
    op.create_index("ix_calls_client_started", "calls", ["client_id", "started_at"])
    op.create_index("ix_calls_provider_call_id", "calls", ["provider_call_id"])


def downgrade() -> None:
    op.drop_index("ix_calls_provider_call_id", table_name="calls")
    op.drop_index("ix_calls_client_started", table_name="calls")
    for t in (
        "audit_logs", "appointments", "integration_accounts", "contact_notes",
        "campaign_contacts", "webhook_deliveries", "webhook_endpoints",
        "api_keys", "credit_transactions",
    ):
        op.drop_table(t)
    for c in (
        "settings", "max_agents", "max_concurrent_calls", "credits_per_minute",
        "credit_balance", "plan", "suspended_at", "suspended_reason", "status",
    ):
        op.drop_column("clients", c)
