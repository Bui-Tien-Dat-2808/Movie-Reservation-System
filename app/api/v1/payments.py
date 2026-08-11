import re
from typing import Dict, Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_active_user, get_db, get_redis
from app.models.user import User
from app.models.reservation import ReservationStatus
from app.services.cache_service import CacheService
from app.services.reservation_service import ReservationService
from datetime import datetime
from app.services.vnpay_service import VNPayService, VN_TZ

router = APIRouter(prefix="/payments", tags=["Payments"])
logger = structlog.get_logger()

vnpay_service = VNPayService()


def get_reservation_service(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> ReservationService:
    return ReservationService(db, CacheService(redis))


class CreatePaymentUrlRequest(BaseModel):
    reservation_id: int = Field(..., description="ID của reservation đang ở trạng thái PENDING")


class CreatePaymentUrlResponse(BaseModel):
    payment_url: str
    vnp_txn_ref: str


@router.post(
    "/create-url",
    response_model=CreatePaymentUrlResponse,
    summary="Tạo URL thanh toán VNPay",
)
async def create_payment_url(
    req: CreatePaymentUrlRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    service: ReservationService = Depends(get_reservation_service),
):
    """
    Tạo VNPay payment URL cho Reservation ở trạng thái PENDING.
    """
    reservation = await service.get_reservation(req.reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đơn đặt vé",
        )

    # Check permission
    if reservation.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền thanh toán đơn đặt vé này",
        )

    if reservation.status != ReservationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Đơn đặt vé đã ở trạng thái {reservation.status.value}, không thể tạo link thanh toán mới",
        )

    # Client IP address
    client_ip = request.client.host if request.client else "127.0.0.1"
    if "x-forwarded-for" in request.headers:
        client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()

    vnp_txn_ref = f"CVN_{reservation.id}_{int(datetime.now(VN_TZ).timestamp())}"
    order_info = f"Thanh toan ve CineVerse {reservation.ticket_code or reservation.id}"

    try:
        payment_url = vnpay_service.create_payment_url(
            vnp_txn_ref=vnp_txn_ref,
            amount=reservation.total_price,
            order_info=order_info,
            client_ip=client_ip,
            return_url=f"{settings.FRONTEND_BASE_URL}/api/v1/payments/vnpay-return",
        )
    except Exception as e:
        logger.exception("Lỗi khi tạo VNPay payment URL cho reservation_id=%s", reservation.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể tạo link thanh toán VNPay: {str(e)}",
        )

    logger.info("vnpay_payment_url_created", reservation_id=reservation.id, vnp_txn_ref=vnp_txn_ref)

    return CreatePaymentUrlResponse(
        payment_url=payment_url,
        vnp_txn_ref=vnp_txn_ref,
    )


@router.get(
    "/vnpay-return",
    summary="VNPay Callback Return URL (Trình duyệt quay lại)",
)
async def vnpay_return(
    request: Request,
    service: ReservationService = Depends(get_reservation_service),
):
    """
    Xử lý khi khách hàng hoàn tất thanh toán trên VNPay và trình duyệt quay lại trang web.
    """
    query_params = dict(request.query_params)
    logger.info("vnpay_return_received", params=query_params)

    is_valid = vnpay_service.verify_response(query_params)
    vnp_txn_ref = query_params.get("vnp_TxnRef", "")
    response_code = query_params.get("vnp_ResponseCode", "")

    # Parse reservation_id from vnp_TxnRef (e.g. CVN_123_1723456789)
    reservation_id = None
    match = re.match(r"^CVN_(\d+)_", vnp_txn_ref)
    if match:
        reservation_id = int(match.group(1))

    # Base frontend URL for redirection — ALWAYS use explicitly configured settings.FRONTEND_BASE_URL.
    # Do NOT infer from request.headers.get("host") which gets overwritten by reverse proxy (e.g. Vite dev server changeOrigin: true).
    frontend_base = settings.FRONTEND_BASE_URL

    if not reservation_id:
        logger.error("vnpay_return_invalid_txn_ref", vnp_txn_ref=vnp_txn_ref)
        return RedirectResponse(url=f"{frontend_base}/payment-result?status=failed&code=INVALID_REF")

    if not is_valid:
        logger.error("vnpay_return_invalid_checksum", vnp_txn_ref=vnp_txn_ref)
        return RedirectResponse(
            url=f"{frontend_base}/payment-result?status=failed&reservation_id={reservation_id}&code=INVALID_CHECKSUM"
        )

    if response_code == "00":
        # Payment successful!
        await service.confirm_payment_success(reservation_id, query_params)
        logger.info("vnpay_payment_success", reservation_id=reservation_id)
        return RedirectResponse(
            url=f"{frontend_base}/payment-result?status=success&reservation_id={reservation_id}"
        )
    else:
        # Payment failed or cancelled by user
        await service.cancel_pending_reservation(
            reservation_id, query_params, reason=f"Giao dịch thất bại (Mã lỗi VNPay: {response_code})"
        )
        logger.warn("vnpay_payment_failed", reservation_id=reservation_id, response_code=response_code)
        return RedirectResponse(
            url=f"{frontend_base}/payment-result?status=failed&reservation_id={reservation_id}&code={response_code}"
        )


@router.api_route(
    "/vnpay-ipn",
    methods=["GET", "POST"],
    summary="VNPay Webhook IPN (Server-to-Server Async Notification)",
)
async def vnpay_ipn(
    request: Request,
    service: ReservationService = Depends(get_reservation_service),
):
    """
    Webhook IPN từ máy chủ VNPay để xác nhận giao dịch bất đồng bộ.
    """
    if request.method == "POST":
        try:
            form_data = await request.form()
            query_params = dict(form_data)
        except Exception:
            query_params = dict(request.query_params)
    else:
        query_params = dict(request.query_params)

    logger.info("vnpay_ipn_received", params=query_params)

    is_valid = vnpay_service.verify_response(query_params)
    if not is_valid:
        return JSONResponse(content={"RspCode": "97", "Message": "Invalid Checksum"})

    vnp_txn_ref = query_params.get("vnp_TxnRef", "")
    response_code = query_params.get("vnp_ResponseCode", "")

    match = re.match(r"^CVN_(\d+)_", vnp_txn_ref)
    if not match:
        return JSONResponse(content={"RspCode": "01", "Message": "Order not found"})

    reservation_id = int(match.group(1))
    reservation = await service.get_reservation(reservation_id)
    if not reservation:
        return JSONResponse(content={"RspCode": "01", "Message": "Order not found"})

    if response_code == "00":
        await service.confirm_payment_success(reservation_id, query_params)
        return JSONResponse(content={"RspCode": "00", "Message": "Confirm Success"})
    else:
        await service.cancel_pending_reservation(
            reservation_id, query_params, reason=f"IPN Failed code {response_code}"
        )
        return JSONResponse(content={"RspCode": "00", "Message": "Confirm Success"})
