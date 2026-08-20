from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class RefundResponse(BaseModel):
    id: int
    reservation_id: int
    payment_transaction_id: int
    amount: Decimal
    vnp_request_id: str
    status: str
    vnpay_response_code: Optional[str] = None
    vnpay_response_message: Optional[str] = None
    admin_note: Optional[str] = None
    resolved_by_admin_id: Optional[int] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime

    # Expanded metadata for Admin & User views
    ticket_code: Optional[str] = None
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None
    movie_title: Optional[str] = None
    payment_method: Optional[str] = "vnpay"
    cancellation_reason: Optional[str] = "Khách hàng huỷ vé"

    model_config = ConfigDict(from_attributes=True)


class RefundResolveRequest(BaseModel):
    admin_note: Optional[str] = "Đã xử lý chuyển khoản hoàn tiền thủ công"


class RefundListResponse(BaseModel):
    items: List[RefundResponse]
    total: int
    page: int
    pageSize: int
    total_pages: int
