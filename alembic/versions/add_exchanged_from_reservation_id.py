"""add exchanged_from_reservation_id column to reservations

Revision ID: add_exchanged_from_reservation_id
Revises: add_refund_transactions_table
Create Date: 2026-08-19 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_exchanged_from_reservation_id'
down_revision = 'add_refund_transactions_table'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('reservations')]
    if 'exchanged_from_reservation_id' not in columns:
        op.add_column('reservations', sa.Column('exchanged_from_reservation_id', sa.Integer(), sa.ForeignKey('reservations.id', ondelete='SET NULL'), nullable=True))


def downgrade() -> None:
    op.drop_column('reservations', 'exchanged_from_reservation_id')
