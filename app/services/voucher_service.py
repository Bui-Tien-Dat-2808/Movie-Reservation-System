from datetime import date, datetime, timezone
from typing import Optional, Tuple, List
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation, ReservationStatus
from app.models.voucher import Voucher, VoucherDiscountType, VoucherRedemption


class VoucherItem(BaseModel):
    code: str
    title: str
    description: str
    discount_type: str
    discount_value: float
    min_spend: float = 0
    max_discount: Optional[float] = None
    expiry_date: str
    bg_gradient: str = "from-amber-500/20 to-yellow-600/10"


class VoucherService:
    """Service for validating voucher codes and calculating discounts using DB."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate_and_calculate_discount(
        self,
        code: str,
        total_amount: float,
        user_id: Optional[int] = None,
    ) -> Tuple[Voucher, float, float]:
        """Validate voucher code against DB constraints and calculate discount."""
        code_upper = code.strip().upper()

        stmt = select(Voucher).where(
            func.upper(Voucher.code) == code_upper,
            Voucher.is_active == True,
        )
        res = await self.db.execute(stmt)
        voucher = res.scalar_one_or_none()

        if not voucher:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mã giảm giá '{code}' không hợp lệ hoặc đã bị vô hiệu hóa.",
            )

        # 1. Expiry date check
        today = date.today()
        if voucher.expiry_date and voucher.expiry_date < today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mã giảm giá '{voucher.code}' đã hết hạn sử dụng vào ngày {voucher.expiry_date.strftime('%d/%m/%Y')}.",
            )

        # 2. Minimum spend check
        if total_amount < voucher.min_spend:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Đơn hàng tối thiểu để áp dụng mã '{voucher.code}' là {voucher.min_spend:,.0f} VNĐ.",
            )

        # 3. Valid weekdays check (0=Monday, 2=Wednesday, etc.)
        if voucher.valid_weekdays and isinstance(voucher.valid_weekdays, list):
            current_weekday = today.weekday()
            if current_weekday not in voucher.valid_weekdays:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Mã giảm giá '{voucher.code}' không áp dụng vào ngày hôm nay.",
                )

        # 4. First booking only check
        if voucher.is_first_booking_only and user_id:
            count_stmt = select(func.count(Reservation.id)).where(
                Reservation.user_id == user_id,
                Reservation.status == ReservationStatus.CONFIRMED,
            )
            booking_count = (await self.db.execute(count_stmt)).scalar_one()
            if booking_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Mã giảm giá '{voucher.code}' chỉ áp dụng cho đơn đặt vé đầu tiên.",
                )

        # 5. Max uses per user check
        if voucher.max_uses_per_user and user_id:
            user_redemptions_stmt = select(func.count(VoucherRedemption.id)).where(
                VoucherRedemption.voucher_id == voucher.id,
                VoucherRedemption.user_id == user_id,
            )
            user_uses = (await self.db.execute(user_redemptions_stmt)).scalar_one()
            if user_uses >= voucher.max_uses_per_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Bạn đã đạt số lần sử dụng tối đa ({voucher.max_uses_per_user} lần) của mã '{voucher.code}'.",
                )

        # 6. Max total uses check
        if voucher.max_uses_total:
            total_redemptions_stmt = select(func.count(VoucherRedemption.id)).where(
                VoucherRedemption.voucher_id == voucher.id,
            )
            total_uses = (await self.db.execute(total_redemptions_stmt)).scalar_one()
            if total_uses >= voucher.max_uses_total:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Mã giảm giá '{voucher.code}' đã hết lượt sử dụng trên hệ thống.",
                )

        # Calculate discount amount
        if voucher.discount_type == VoucherDiscountType.PERCENT or voucher.discount_type == "percent":
            discount = (total_amount * voucher.discount_value) / 100.0
            if voucher.max_discount and discount > voucher.max_discount:
                discount = voucher.max_discount
        else:
            discount = voucher.discount_value

        discount = min(discount, total_amount)
        final_amount = max(0.0, total_amount - discount)

        return voucher, discount, final_amount

    async def record_redemption(self, voucher_id: int, user_id: int, reservation_id: int) -> VoucherRedemption:
        """Record a voucher redemption entry in database."""
        redemption = VoucherRedemption(
            voucher_id=voucher_id,
            user_id=user_id,
            reservation_id=reservation_id,
            redeemed_at=datetime.now(timezone.utc),
        )
        self.db.add(redemption)
        await self.db.flush()
        return redemption
