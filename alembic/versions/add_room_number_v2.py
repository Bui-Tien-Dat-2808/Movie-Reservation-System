"""add room number v2

Revision ID: add_room_number_v2
Revises: 5f6e7d8c9a0b
Create Date: 2026-08-05 15:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
sqla = sa

# revision identifiers, used by Alembic.
revision = 'add_room_number_v2'
down_revision = '5f6e7d8c9a0b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sqla.inspect(conn)

    # 1. Add room_number column with server_default='1'
    columns = [c['name'] for c in inspector.get_columns('rooms')]
    if 'room_number' not in columns:
        op.add_column('rooms', sqla.Column('room_number', sqla.Integer(), nullable=False, server_default='1'))

    # 2. Add Unique Constraint on (room_type, room_number)
    constraints = [c['name'] for c in inspector.get_unique_constraints('rooms')]
    if 'uq_rooms_type_number' not in constraints:
        op.create_unique_constraint('uq_rooms_type_number', 'rooms', ['room_type', 'room_number'])


def downgrade() -> None:
    op.drop_constraint('uq_rooms_type_number', 'rooms', type_='unique')
    op.drop_column('rooms', 'room_number')
