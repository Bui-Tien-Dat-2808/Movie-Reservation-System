"""add vouchers and redemption tables

Revision ID: 5f6e7d8c9a0b
Revises: 4e5d6c7b8a90
Create Date: 2026-08-04 10:47:00.000000

"""
from alembic import op
import sqlalchemy as sa
sqla = sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5f6e7d8c9a0b'
down_revision = 'normalize_13_vietnamese_genres'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Create enum type for postgresql if needed
    voucher_discount_type = postgresql.ENUM('percent', 'fixed', name='voucherdiscounttype', create_type=False)
    voucher_discount_type.create(conn, checkfirst=True)

    # 2. Create vouchers table
    if not inspector.has_table('vouchers'):
        op.create_table(
            'vouchers',
            sqla.Column('id', sqla.Integer(), nullable=False),
            sqla.Column('code', sqla.String(length=50), nullable=False),
            sqla.Column('discount_type', sqla.Enum('percent', 'fixed', name='voucherdiscounttype'), nullable=False),
            sqla.Column('discount_value', sqla.Float(), nullable=False),
            sqla.Column('min_spend', sqla.Float(), nullable=False, server_default='0.0'),
            sqla.Column('max_discount', sqla.Float(), nullable=True),
            sqla.Column('expiry_date', sqla.Date(), nullable=True),
            sqla.Column('valid_weekdays', sqla.JSON(), nullable=True),
            sqla.Column('is_first_booking_only', sqla.Boolean(), nullable=False, server_default='false'),
            sqla.Column('max_uses_total', sqla.Integer(), nullable=True),
            sqla.Column('max_uses_per_user', sqla.Integer(), nullable=True),
            sqla.Column('is_active', sqla.Boolean(), nullable=False, server_default='true'),
            sqla.Column('created_at', sqla.DateTime(timezone=True), server_default=sqla.text('now()'), nullable=False),
            sqla.Column('updated_at', sqla.DateTime(timezone=True), server_default=sqla.text('now()'), nullable=False),
            sqla.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_vouchers_code'), 'vouchers', ['code'], unique=True)
        op.create_index(op.f('ix_vouchers_id'), 'vouchers', ['id'], unique=False)

    # 3. Create voucher_redemptions table
    if not inspector.has_table('voucher_redemptions'):
        op.create_table(
            'voucher_redemptions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('voucher_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('reservation_id', sa.Integer(), nullable=False),
            sa.Column('redeemed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['voucher_id'], ['vouchers.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_voucher_redemptions_id'), 'voucher_redemptions', ['id'], unique=False)
        op.create_index(op.f('ix_voucher_redemptions_reservation_id'), 'voucher_redemptions', ['reservation_id'], unique=False)
        op.create_index(op.f('ix_voucher_redemptions_user_id'), 'voucher_redemptions', ['user_id'], unique=False)
        op.create_index(op.f('ix_voucher_redemptions_voucher_id'), 'voucher_redemptions', ['voucher_id'], unique=False)

    # 4. Seed initial default vouchers if table is empty
    if inspector.has_table('vouchers'):
        voucher_count = conn.execute(sa.text("SELECT COUNT(*) FROM vouchers")).scalar()
        if voucher_count == 0:
            vouchers_table = sa.sql.table(
                'vouchers',
                sa.sql.column('code', sa.String),
                sa.sql.column('discount_type', sa.Enum('percent', 'fixed', name='voucherdiscounttype')),
                sa.sql.column('discount_value', sa.Float),
                sa.sql.column('min_spend', sa.Float),
                sa.sql.column('max_discount', sa.Float),
                sa.sql.column('expiry_date', sa.Date),
                sa.sql.column('valid_weekdays', sa.JSON),
                sa.sql.column('is_first_booking_only', sa.Boolean),
                sa.sql.column('max_uses_total', sa.Integer),
                sa.sql.column('max_uses_per_user', sa.Integer),
                sa.sql.column('is_active', sa.Boolean)
            )

            op.bulk_insert(vouchers_table, [
                {
                    "code": "WELCOME10",
                    "discount_type": "percent",
                    "discount_value": 10.0,
                    "min_spend": 100000.0,
                    "max_discount": 50000.0,
                    "expiry_date": "2026-12-31",
                    "valid_weekdays": None,
                    "is_first_booking_only": False,
                    "max_uses_total": None,
                    "max_uses_per_user": 1,
                    "is_active": True,
                },
                {
                    "code": "HAPPYWED",
                    "discount_type": "fixed",
                    "discount_value": 30000.0,
                    "min_spend": 150000.0,
                    "max_discount": None,
                    "expiry_date": "2026-12-31",
                    "valid_weekdays": [2],  # Wednesday only
                    "is_first_booking_only": False,
                    "max_uses_total": None,
                    "max_uses_per_user": None,
                    "is_active": True,
                },
                {
                    "code": "CINEVERSE10",
                    "discount_type": "percent",
                    "discount_value": 10.0,
                    "min_spend": 0.0,
                    "max_discount": 100000.0,
                    "expiry_date": "2026-12-31",
                    "valid_weekdays": None,
                    "is_first_booking_only": True,  # First booking only
                    "max_uses_total": None,
                    "max_uses_per_user": 1,
                    "is_active": True,
                },
                {
                    "code": "VIPMOVIE",
                    "discount_type": "fixed",
                    "discount_value": 50000.0,
                    "min_spend": 200000.0,
                    "max_discount": None,
                    "expiry_date": "2026-12-31",
                    "valid_weekdays": None,
                    "is_first_booking_only": False,
                    "max_uses_total": 500,
                    "max_uses_per_user": 2,
                    "is_active": True,
                },
            ])


def downgrade() -> None:
    op.drop_table('voucher_redemptions')
    op.drop_table('vouchers')
    op.execute("DROP TYPE IF EXISTS voucherdiscounttype;")
