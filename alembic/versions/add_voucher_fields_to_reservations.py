"""Add voucher_code and discount_amount to reservations

Revision ID: add_voucher_fields_reservation
Revises: ed44325d752b
Create Date: 2026-08-03 15:12:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_voucher_fields_reservation'
down_revision: Union[str, None] = 'ed44325d752b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('reservations')]
    if 'voucher_code' not in columns:
        op.add_column('reservations', sa.Column('voucher_code', sa.String(length=50), nullable=True))
    if 'discount_amount' not in columns:
        op.add_column('reservations', sa.Column('discount_amount', sa.Numeric(precision=10, scale=2), server_default='0.00', nullable=False))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('reservations')]
    if 'discount_amount' in columns:
        op.drop_column('reservations', 'discount_amount')
    if 'voucher_code' in columns:
        op.drop_column('reservations', 'voucher_code')
