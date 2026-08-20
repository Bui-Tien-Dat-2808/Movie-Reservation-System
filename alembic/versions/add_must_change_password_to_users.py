"""Add must_change_password column to users table

Revision ID: add_must_change_password_to_users
Revises: add_refund_transactions_table
Create Date: 2026-08-12 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_must_change_pwd'
down_revision: Union[str, None] = 'add_exchanged_from_res_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('users')]
    if 'must_change_password' not in columns:
        op.add_column(
            'users',
            sa.Column('must_change_password', sa.Boolean(), server_default='false', nullable=False)
        )


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
