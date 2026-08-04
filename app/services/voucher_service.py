from typing import List, Optional, Tuple
from fastapi import HTTPException, status
from pydantic import BaseModel

class VoucherItem(BaseModel):
    code: str
    title: str
    description: str
    discount_type: str  # "percent" or "fixed"
    discount_value: float  # e.g., 10 for 10% or 30000 for 30k
    min_spend: float = 0
    max_discount: Optional[float] = None
    expiry_date: str
    bg_gradient: str


PROMOTIONS_LIST: List[VoucherItem] = [
    VoucherItem(
        code="CINEVERSE10",
        title="Ưu Đãi Tân Thủ CineVerse",
        description="Giảm ngay 10% cho mọi đơn đặt vé lần đầu tiên tại website CineVerse.",
        discount_type="percent",
        discount_value=10,
        min_spend=0,
        max_discount=50000,
        expiry_date="2026-12-31",
        bg_gradient="from-amber-500/20 to-yellow-600/10",
    ),
    VoucherItem(
        code="HSSV20",
        title="Đặc Quyền Học Sinh - Sinh Viên",
        description="Giảm 20% tổng hóa đơn vé xem phim áp dụng từ Thứ 2 đến Thứ 5 hàng tuần.",
        discount_type="percent",
        discount_value=20,
        min_spend=70000,
        max_discount=60000,
        expiry_date="2026-12-31",
        bg_gradient="from-blue-500/20 to-indigo-600/10",
    ),
    VoucherItem(
        code="HAPPYWED",
        title="Thứ 4 Vui Vẻ - Siêu Ưu Đãi Đồng Giá",
        description="Giảm 30.000 VNĐ cho mọi cặp vé xem phim áp dụng vào ngày Thứ 4 hàng tuần.",
        discount_type="fixed",
        discount_value=30000,
        min_spend=150000,
        expiry_date="2026-12-31",
        bg_gradient="from-purple-500/20 to-pink-600/10",
    ),
    VoucherItem(
        code="IMAXVIP",
        title="Ưu Đãi Trải Nghiệm Màn Hình IMAX 3D",
        description="Giảm 15% cho vé phòng IMAX 3D và 4DX vào các suất chiếu cuối tuần.",
        discount_type="percent",
        discount_value=15,
        min_spend=200000,
        max_discount=100000,
        expiry_date="2026-12-31",
        bg_gradient="from-[#e8b84b]/20 to-amber-700/10",
    ),
]


class VoucherService:
    """Service for validating voucher codes and calculating discounts."""

    @staticmethod
    def validate_and_calculate_discount(code: str, total_amount: float) -> Tuple[VoucherItem, float, float]:
        """
        Validate voucher code against total amount and return (voucher_item, discount_amount, final_amount).
        Raises HTTPException HTTP_404_NOT_FOUND if voucher is invalid/expired.
        Raises HTTPException HTTP_400_BAD_REQUEST if total_amount < min_spend.
        """
        code_upper = code.strip().upper()
        match = next((v for v in PROMOTIONS_LIST if v.code.upper() == code_upper), None)

        if not match:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mã giảm giá '{code}' không hợp lệ hoặc đã hết hạn.",
            )

        if total_amount < match.min_spend:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Đơn hàng tối thiểu để áp dụng mã '{match.code}' là {match.min_spend:,.0f} VNĐ.",
            )

        if match.discount_type == "percent":
            discount = (total_amount * match.discount_value) / 100
            if match.max_discount and discount > match.max_discount:
                discount = match.max_discount
        else:
            discount = match.discount_value

        discount = min(discount, total_amount)
        final_amount = max(0.0, total_amount - discount)

        return match, discount, final_amount
