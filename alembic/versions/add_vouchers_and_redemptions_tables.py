"""add vouchers and redemption tables

Revision ID: 5f6e7d8c9a0b
Revises: 4e5d6c7b8a90
Create Date: 2026-08-04 10:47:00.000000

"""
from alembic import op
import sqlalchemy as sqla
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5f6e7d8c9a0b'
down_revision = None  # Or latest revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create enum type for postgresql if needed
    voucher_discount_type = postgresql.ENUM('percent', 'fixed', name='voucherdiscounttype', create_type=False)
    voucher_discount_type.create(op.get_bind(), checkfirst=True)

    # 2. Create vouchers table
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
    op.create_table(
        'voucher_redemptions',
        sqla.Column('id', sqla.Integer(), nullable=False),
        sqla.Column('voucher_id', sqla.Integer(), nullable=False),
        sqla.Column('user_id', sqla.Integer(), nullable=False),
        sqla.Column('reservation_id', sqla.Integer(), nullable=False),
        sqla.Column('redeemed_at', sqla.DateTime(timezone=True), server_default=sqla.text('now()'), nullable=False),
        sqla.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
        sqla.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sqla.ForeignKeyConstraint(['voucher_id'], ['vouchers.id'], ondelete='CASCADE'),
        sqla.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_voucher_redemptions_id'), 'voucher_redemptions', ['id'], unique=False)
    op.create_index(op.f('ix_voucher_redemptions_reservation_id'), 'voucher_redemptions', ['reservation_id'], unique=False)
    op.create_index(op.f('ix_voucher_redemptions_user_id'), 'voucher_redemptions', ['user_id'], unique=False)
    op.create_index(op.f('ix_voucher_redemptions_voucher_id'), 'voucher_redemptions', ['voucher_id'], unique=False)

    # 4. Seed initial default vouchers
    vouchers_table = sqla.sql.table(
        'vouchers',
        sqla.sql.column('code', sqla.String),
        sqla.sql.column('discount_type', sqla.Enum('percent', 'fixed', name='voucherdiscounttype')),
        sqla.sql.column('discount_value', sqla.Float),
        sqla.sql.column('min_spend', sqla.Float),
        sqla.sql.column('max_discount', sqla.Float),
        sqla.sql.column('expiry_date', sqla.Date),
        sqla.sql.column('valid_weekdays', sqla.JSON),
        sqla.sql.column('is_first_booking_only', sqla.Boolean),
        sqla.sql.column('max_uses_total', sqla.Integer),
        sqla.sql.column('max_uses_per_user', sqla.Integer),
        sqla.sql.column('is_active', sqla.Boolean)
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
