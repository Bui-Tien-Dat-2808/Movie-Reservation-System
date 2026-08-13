"""add popularity column to movies

Revision ID: add_popularity_to_movies
Revises: add_couple_seats_and_price
Create Date: 2026-08-12 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_popularity_to_movies'
down_revision = 'add_ticket_code_to_reservations'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns_movies = [c['name'] for c in inspector.get_columns('movies')]
    if 'popularity' not in columns_movies:
        op.add_column('movies', sa.Column('popularity', sa.Float(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('movies', 'popularity')
