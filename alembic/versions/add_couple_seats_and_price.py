"""add couple seats and couple price

Revision ID: add_couple_seats_and_price
Revises: add_room_number_v2
Create Date: 2026-08-06 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
sqla = sa

# revision identifiers, used by Alembic.
revision = 'add_couple_seats_and_price'
down_revision = 'add_room_number_v2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sqla.inspect(conn)

    # 1. Add width column to seats table if missing
    columns_seats = [c['name'] for c in inspector.get_columns('seats')]
    if 'width' not in columns_seats:
        op.add_column('seats', sqla.Column('width', sqla.Integer(), nullable=False, server_default='1'))

    # 2. Add couple_price column to showtimes table if missing
    columns_showtimes = [c['name'] for c in inspector.get_columns('showtimes')]
    if 'couple_price' not in columns_showtimes:
        op.add_column('showtimes', sqla.Column('couple_price', sqla.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('showtimes', 'couple_price')
    op.drop_column('seats', 'width')
