"""add reviews table and custom_options to reservation_concessions

Revision ID: add_reviews_and_options
Revises: add_missing_performance_indexes
Create Date: 2026-08-25 10:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_reviews_and_options'
down_revision = 'add_missing_performance_indexes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Add custom_options column to reservation_concessions
    rc_columns = [col['name'] for col in inspector.get_columns('reservation_concessions')]
    if 'custom_options' not in rc_columns:
        op.add_column('reservation_concessions', sa.Column('custom_options', sa.Text(), nullable=True))

    # 2. Create reviews table if not exists
    tables = inspector.get_table_names()
    if 'reviews' not in tables:
        op.create_table(
            'reviews',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('movie_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('is_verified_booking', sa.Boolean(), server_default='false', nullable=False),
            sa.Column('is_approved', sa.Boolean(), server_default='true', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['movie_id'], ['movies.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_reviews_movie_id', 'reviews', ['movie_id'], unique=False)
        op.create_index('ix_reviews_user_id', 'reviews', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('reviews')
    op.drop_column('reservation_concessions', 'custom_options')
