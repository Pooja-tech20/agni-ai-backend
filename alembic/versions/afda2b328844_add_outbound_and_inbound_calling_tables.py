"""add outbound and inbound calling tables

Revision ID: afda2b328844
Revises: e5f9b2c8a1d4
Create Date: 2026-10-10 10:29:10.214679

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'afda2b328844'
down_revision: Union[str, None] = 'e5f9b2c8a1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('contacts',
    sa.Column('client_id', sa.UUID(), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('phone_numbers',
    sa.Column('client_id', sa.UUID(), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.Column('provider', sa.String(length=50), server_default='mock', nullable=False),
    sa.Column('provider_number_id', sa.String(length=120), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('inbound_agent_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['inbound_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('campaigns',
    sa.Column('client_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=30), server_default='draft', nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('phone_number_id', sa.UUID(), nullable=True),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('total_calls', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('running_calls', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('successful_calls', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['phone_number_id'], ['phone_numbers.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('inbound_routes',
    sa.Column('client_id', sa.UUID(), nullable=False),
    sa.Column('phone_number_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default='UTC', nullable=False),
    sa.Column('max_concurrent_calls', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('budget_credits', sa.Integer(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('call_window_start', sa.Time(), nullable=True),
    sa.Column('call_window_end', sa.Time(), nullable=True),
    sa.Column('active_days', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['phone_number_id'], ['phone_numbers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('calls', sa.Column('campaign_id', sa.UUID(), nullable=True))
    op.add_column('calls', sa.Column('inbound_route_id', sa.UUID(), nullable=True))
    op.add_column('calls', sa.Column('provider_call_id', sa.String(length=120), nullable=True))
    op.create_foreign_key('fk_calls_campaign_id', 'calls', 'campaigns', ['campaign_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_calls_inbound_route_id', 'calls', 'inbound_routes', ['inbound_route_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_calls_inbound_route_id', 'calls', type_='foreignkey')
    op.drop_constraint('fk_calls_campaign_id', 'calls', type_='foreignkey')
    op.drop_column('calls', 'provider_call_id')
    op.drop_column('calls', 'inbound_route_id')
    op.drop_column('calls', 'campaign_id')
    op.drop_table('inbound_routes')
    op.drop_table('campaigns')
    op.drop_table('phone_numbers')
    op.drop_table('contacts')