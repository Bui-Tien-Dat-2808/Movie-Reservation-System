from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from app.models.voucher import VoucherDiscountType


class VoucherBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    discount_type: VoucherDiscountType = VoucherDiscountType.PERCENT
    discount_value: float = Field(..., gt=0)
    min_spend: float = Field(0.0, ge=0)
    max_discount: Optional[float] = Field(None, ge=0)
    expiry_date: Optional[date] = None
    valid_weekdays: Optional[List[int]] = None
    is_first_booking_only: bool = False
    max_uses_total: Optional[int] = Field(None, ge=1)
    max_uses_per_user: Optional[int] = Field(None, ge=1)
    is_active: bool = True


class VoucherCreate(VoucherBase):
    pass


class VoucherUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    discount_type: Optional[VoucherDiscountType] = None
    discount_value: Optional[float] = Field(None, gt=0)
    min_spend: Optional[float] = Field(None, ge=0)
    max_discount: Optional[float] = Field(None, ge=0)
    expiry_date: Optional[date] = None
    valid_weekdays: Optional[List[int]] = None
    is_first_booking_only: Optional[bool] = None
    max_uses_total: Optional[int] = Field(None, ge=1)
    max_uses_per_user: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None


class VoucherResponse(VoucherBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
