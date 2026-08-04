from typing import List
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.services.voucher_service import PROMOTIONS_LIST, VoucherItem, VoucherService

router = APIRouter(prefix="/vouchers", tags=["Vouchers & Promotions"])


class ApplyVoucherRequest(BaseModel):
    code: str
    total_amount: float


class ApplyVoucherResponse(BaseModel):
    valid: bool
    code: str
    discount_amount: float
    final_amount: float
    message: str


@router.get("/", response_model=List[VoucherItem], summary="Get active promotions & vouchers")
async def list_vouchers():
    """Public: List all active promotional offers and voucher codes."""
    return PROMOTIONS_LIST


@router.post("/apply", response_model=ApplyVoucherResponse, summary="Apply voucher code")
async def apply_voucher(req: ApplyVoucherRequest):
    """Validate and calculate discount for a voucher code."""
    match, discount, final_amount = VoucherService.validate_and_calculate_discount(
        req.code, req.total_amount
    )

    return ApplyVoucherResponse(
        valid=True,
        code=match.code,
        discount_amount=discount,
        final_amount=final_amount,
        message=f"Đã áp dụng thành công mã {match.code}! Bạn được giảm {discount:,.0f} VNĐ.",
    )
