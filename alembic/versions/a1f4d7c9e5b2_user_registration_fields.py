"""user registration fields

Revision ID: a1f4d7c9e5b2
Revises: c2b8e3a3b201
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1f4d7c9e5b2'
down_revision: Union[str, None] = 'c2b8e3a3b201'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('first_name', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('last_name', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('organization_name', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('phone_country_code', sa.String(length=8), nullable=True))
    op.add_column('users', sa.Column('phone_number', sa.String(length=20), nullable=True))
    op.add_column('users', sa.Column('referral_source', sa.String(length=50), nullable=True))

    # Backfill existing users
    op.execute("""
        UPDATE users SET
            first_name = COALESCE(NULLIF(split_part(full_name, ' ', 1), ''), split_part(email, '@', 1)),
            last_name = COALESCE(NULLIF(trim(substr(full_name, length(split_part(full_name, ' ', 1)) + 1)), ''), ''),
            organization_name = '',
            phone_country_code = '',
            phone_number = ''
    """)

    op.alter_column('users', 'first_name', nullable=False)
    op.alter_column('users', 'last_name', nullable=False)
    op.alter_column('users', 'organization_name', nullable=False)
    op.alter_column('users', 'phone_country_code', nullable=False)
    op.alter_column('users', 'phone_number', nullable=False)

    op.drop_column('users', 'full_name')


def downgrade() -> None:
    op.add_column('users', sa.Column('full_name', sa.String(length=255), nullable=True))
    op.execute("UPDATE users SET full_name = trim(first_name || ' ' || last_name)")
    op.drop_column('users', 'referral_source')
    op.drop_column('users', 'phone_number')
    op.drop_column('users', 'phone_country_code')
    op.drop_column('users', 'organization_name')
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')