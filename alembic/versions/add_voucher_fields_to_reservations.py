"""Add voucher_code and discount_amount to reservations

Revision ID: add_voucher_fields_to_reservations
Revises: ed44325d752b
Create Date: 2026-08-03 15:12:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_voucher_fields_to_reservations'
down_revision: Union[str, None] = 'ed44325d752b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reservations', sa.Column('voucher_code', sa.String(length=50), nullable=True))
    op.add_column('reservations', sa.Column('discount_amount', sa.Numeric(precision=10, scale=2), server_default='0.00', nullable=False))


def downgrade() -> None:
    op.drop_column('reservations', 'discount_amount')
    op.drop_column('reservations', 'voucher_code')
