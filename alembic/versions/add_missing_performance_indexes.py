"""add missing performance indexes on foreign keys and frequently filtered columns

Revision ID: add_missing_performance_indexes
Revises: add_exchanged_from_res_id
Create Date: 2026-08-25 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_missing_performance_indexes'
down_revision = 'add_must_change_pwd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Index on payment_transactions.reservation_id
    pt_indexes = [idx['name'] for idx in inspector.get_indexes('payment_transactions')]
    if 'ix_payment_transactions_reservation_id' not in pt_indexes:
        op.create_index('ix_payment_transactions_reservation_id', 'payment_transactions', ['reservation_id'], unique=False)

    # 2. Index on reservations.exchanged_from_reservation_id
    res_indexes = [idx['name'] for idx in inspector.get_indexes('reservations')]
    if 'ix_reservations_exchanged_from_reservation_id' not in res_indexes:
        op.create_index('ix_reservations_exchanged_from_reservation_id', 'reservations', ['exchanged_from_reservation_id'], unique=False)

    # 3. Index on point_transactions.user_id
    point_indexes = [idx['name'] for idx in inspector.get_indexes('point_transactions')]
    if 'ix_point_transactions_user_id' not in point_indexes:
        op.create_index('ix_point_transactions_user_id', 'point_transactions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_point_transactions_user_id', table_name='point_transactions')
    op.drop_index('ix_reservations_exchanged_from_reservation_id', table_name='reservations')
    op.drop_index('ix_payment_transactions_reservation_id', table_name='payment_transactions')

