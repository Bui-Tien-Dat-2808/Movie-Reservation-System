"""add reservation exchanged status

Revision ID: add_reservation_exchanged_status
Revises: add_couple_seats_and_price
Create Date: 2026-08-06 10:44:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_reservation_exchanged_status'
down_revision = 'add_couple_seats_and_price'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres enum type update if enum constraint exists
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("ALTER TYPE reservationstatus ADD VALUE IF NOT EXISTS 'exchanged';")


def downgrade() -> None:
    pass
