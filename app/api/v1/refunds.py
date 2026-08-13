from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.models.user import User
from app.schemas.refund import (
    RefundListResponse,
    RefundResolveRequest,
    RefundResponse,
)
from app.services.refund_service import RefundService

router = APIRouter(prefix="/admin/refunds", tags=["Admin - Refunds"])


def get_refund_service(db: AsyncSession = Depends(get_db)) -> RefundService:
    return RefundService(db)


@router.get(
    "",
    response_model=RefundListResponse,
    summary="List refund requests (Admin)",
)
async def list_refunds(
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status (manual_required, success, processing, failed, all)"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    service: RefundService = Depends(get_refund_service),
):
    """Admin: List all refund transactions with optional status filtering."""
    items, total = await service.list_refunds(status_filter=status_filter, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return RefundListResponse(
        items=[RefundResponse(**item) for item in items],
        total=total,
        page=page,
        pageSize=page_size,
        total_pages=total_pages,
    )


@router.post(
    "/{refund_id}/resolve",
    response_model=RefundResponse,
    summary="Mark refund resolved manually (Admin)",
)
async def resolve_refund_manually(
    refund_id: int,
    body: Optional[RefundResolveRequest] = None,
    current_user: User = Depends(require_admin),
    service: RefundService = Depends(get_refund_service),
):
    """Admin: Mark a refund as resolved manually (e.g. money transferred outside system)."""
    admin_note = body.admin_note if body else "Đã xử lý chuyển khoản hoàn tiền thủ công"
    refund = await service.resolve_refund_manually(refund_id, current_user.id, admin_note)
    return RefundResponse.model_validate(refund)


@router.post(
    "/{refund_id}/retry",
    response_model=RefundResponse,
    summary="Retry calling VNPay refund API (Admin)",
)
async def retry_refund(
    refund_id: int,
    current_user: User = Depends(require_admin),
    service: RefundService = Depends(get_refund_service),
):
    """Admin: Retry initiating VNPay refund API for failed or manual_required refunds."""
    refund = await service.retry_refund(refund_id)
    return RefundResponse.model_validate(refund)
