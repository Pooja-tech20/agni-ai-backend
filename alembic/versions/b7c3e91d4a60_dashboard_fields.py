"""dashboard fields

Revision ID: b7c3e91d4a60
Revises: a1f4d7c9e5b2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7c3e91d4a60'
down_revision: Union[str, None] = 'a1f4d7c9e5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('client_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_users_client_id'), 'users', ['client_id'])
    op.create_foreign_key('fk_users_client_id', 'users', 'clients', ['client_id'], ['id'], ondelete='SET NULL')
    op.add_column('users', sa.Column('credits', sa.Integer(), server_default='10', nullable=False))
    op.add_column('calls', sa.Column('direction', sa.String(length=20), server_default='inbound', nullable=False))
    op.add_column('calls', sa.Column('converted', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('calls', 'converted')
    op.drop_column('calls', 'direction')
    op.drop_column('users', 'credits')
    op.drop_constraint('fk_users_client_id', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_client_id'), table_name='users')
    op.drop_column('users', 'client_id')