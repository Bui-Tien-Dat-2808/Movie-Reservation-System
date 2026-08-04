import asyncio
from datetime import date
from sqlalchemy import select
from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.models.voucher import Voucher, VoucherDiscountType


async def init_vouchers():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # Check existing vouchers
        res = await session.execute(select(Voucher))
        existing = res.scalars().all()
        if not existing:
            vouchers = [
                Voucher(
                    code="WELCOME10",
                    discount_type=VoucherDiscountType.PERCENT,
                    discount_value=10.0,
                    min_spend=100000.0,
                    max_discount=50000.0,
                    expiry_date=date(2026, 12, 31),
                    valid_weekdays=None,
                    is_first_booking_only=False,
                    max_uses_total=None,
                    max_uses_per_user=1,
                    is_active=True,
                ),
                Voucher(
                    code="HAPPYWED",
                    discount_type=VoucherDiscountType.FIXED,
                    discount_value=30000.0,
                    min_spend=150000.0,
                    max_discount=None,
                    expiry_date=date(2026, 12, 31),
                    valid_weekdays=[2],  # Wednesday only
                    is_first_booking_only=False,
                    max_uses_total=None,
                    max_uses_per_user=None,
                    is_active=True,
                ),
                Voucher(
                    code="CINEVERSE10",
                    discount_type=VoucherDiscountType.PERCENT,
                    discount_value=10.0,
                    min_spend=0.0,
                    max_discount=100000.0,
                    expiry_date=date(2026, 12, 31),
                    valid_weekdays=None,
                    is_first_booking_only=True,
                    max_uses_total=None,
                    max_uses_per_user=1,
                    is_active=True,
                ),
                Voucher(
                    code="VIPMOVIE",
                    discount_type=VoucherDiscountType.FIXED,
                    discount_value=50000.0,
                    min_spend=200000.0,
                    max_discount=None,
                    expiry_date=date(2026, 12, 31),
                    valid_weekdays=None,
                    is_first_booking_only=False,
                    max_uses_total=500,
                    max_uses_per_user=2,
                    is_active=True,
                ),
            ]
            session.add_all(vouchers)
            await session.commit()
            print("Initialized default vouchers in DB:", [v.code for v in vouchers])
        else:
            print("Vouchers table already populated:", [v.code for v in existing])


if __name__ == "__main__":
    asyncio.run(init_vouchers())
