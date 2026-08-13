"""add refund_transactions table

Revision ID: add_refund_transactions_table
Revises: add_popularity_to_movies
Create Date: 2026-08-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_refund_transactions_table'
down_revision = 'add_popularity_to_movies'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    tables = inspector.get_table_names()
    if 'refund_transactions' not in tables:
        op.create_table(
            'refund_transactions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('reservation_id', sa.Integer(), nullable=False),
            sa.Column('payment_transaction_id', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Numeric(10, 2), nullable=False),
            sa.Column('vnp_request_id', sa.String(100), nullable=False),
            sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
            sa.Column('vnpay_response_code', sa.String(50), nullable=True),
            sa.Column('vnpay_response_message', sa.String(255), nullable=True),
            sa.Column('admin_note', sa.String(500), nullable=True),
            sa.Column('resolved_by_admin_id', sa.Integer(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['payment_transaction_id'], ['payment_transactions.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['resolved_by_admin_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_refund_transactions_reservation_id'), 'refund_transactions', ['reservation_id'], unique=False)
        op.create_index(op.f('ix_refund_transactions_vnp_request_id'), 'refund_transactions', ['vnp_request_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_refund_transactions_vnp_request_id'), table_name='refund_transactions')
    op.drop_index(op.f('ix_refund_transactions_reservation_id'), table_name='refund_transactions')
    op.drop_table('refund_transactions')
