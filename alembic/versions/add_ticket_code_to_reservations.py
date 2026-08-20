"""add ticket code to reservations

Revision ID: add_ticket_code_to_reservations
Revises: add_reservation_exchanged_status
Create Date: 2026-08-06 10:53:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_ticket_code_to_reservations'
down_revision = 'add_reservation_exchanged_status'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('reservations')]
    if 'ticket_code' not in columns:
        op.add_column('reservations', sa.Column('ticket_code', sa.String(length=50), nullable=True))
    indexes = [i['name'] for i in inspector.get_indexes('reservations')]
    if 'ix_reservations_ticket_code' not in indexes:
        op.create_index(op.f('ix_reservations_ticket_code'), 'reservations', ['ticket_code'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_reservations_ticket_code'), table_name='reservations')
    op.drop_column('reservations', 'ticket_code')
