import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import httpx
import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import NotFoundException, ValidationException
from app.models.payment import PaymentTransaction
from app.models.refund import RefundTransaction
from app.models.reservation import Reservation
from app.models.showtime import Showtime
from app.models.user import User

logger = structlog.get_logger()
VN_TZ = timezone(timedelta(hours=7))

# URL API hoàn tiền — LƯU Ý: khác host/path với URL thanh toán (vpcpay.html)
VNPAY_REFUND_URL = "https://sandbox.vnpayment.vn/merchant_webapi/api/transaction"


class RefundService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.vnp_tmn_code = getattr(settings, "VNPAY_TMN_CODE", "S6967RVA")
        self.vnp_hash_secret = getattr(settings, "VNPAY_HASH_SECRET", "NTDXCYCSAOPNANKALKQZICSVHTRLIKUX")

    async def initiate_refund(
        self, payment: PaymentTransaction, reason: str, amount: Optional[Decimal] = None
    ) -> RefundTransaction:
        """Initiate refund for a paid reservation."""
        refund_amount = amount or payment.amount
        vnp_request_id = f"RF{uuid.uuid4().hex[:16]}"

        refund = RefundTransaction(
            reservation_id=payment.reservation_id,
            payment_transaction_id=payment.id,
            amount=refund_amount,
            vnp_request_id=vnp_request_id,
            status="processing",
        )
        self.db.add(refund)
        await self.db.flush()

        try:
            result = await self._call_vnpay_refund_api(payment, refund_amount, vnp_request_id, reason)
            response_code = result.get("vnp_ResponseCode")
            if response_code == "00":
                refund.status = "success"
                refund.vnpay_response_message = result.get("vnp_Message") or "Hoàn tiền tự động thành công qua VNPay"
            else:
                # VNPay từ chối/lỗi -> cần admin xử lý thủ công (rất có thể do giới hạn sandbox)
                refund.status = "manual_required"
                refund.vnpay_response_message = result.get("vnp_Message") or f"VNPay từ chối (Mã {response_code})"
            refund.vnpay_response_code = response_code
        except Exception as e:
            logger.exception("Lỗi gọi API hoàn tiền VNPay", vnp_request_id=vnp_request_id)
            refund.status = "manual_required"
            refund.vnpay_response_message = f"Lỗi kết nối API VNPay: {str(e)}"

        await self.db.flush()

        # Trigger refund email notification
        is_success = (refund.status == "success")
        note_or_reason = "Xác nhận hoàn tiền thành công cho khách" if is_success else "Không thể hoàn tự động qua VNPAY"
        await self._trigger_refund_email(refund.id, is_success=is_success, note_or_reason=note_or_reason)

        return refund

    async def _trigger_refund_email(self, refund_id: int, is_success: bool, note_or_reason: str):
        """Helper to safely extract user and movie details and trigger thread-safe refund email."""
        try:
            r = await self.get_refund(refund_id)
            user = r.reservation.user if r.reservation else None
            showtime = r.reservation.showtime if r.reservation else None
            movie = showtime.movie if showtime and getattr(showtime, "movie", None) else None

            if user and user.email:
                ticket_code = r.reservation.ticket_code if r.reservation else f"#{r.reservation_id}"
                movie_title = movie.title if movie else "Xem Phim CineVerse"
                amount = r.amount

                import asyncio
                from app.services.email_service import EmailService
                from app.utils.background import fire_and_forget
                fire_and_forget(
                    asyncio.to_thread(
                        EmailService.send_refund_notification_email,
                        user.email,
                        ticket_code,
                        movie_title,
                        amount,
                        is_success,
                        note_or_reason,
                    )
                )
        except Exception as e:
            logger.warning("trigger_refund_email_failed", refund_id=refund_id, error=str(e))

    async def _call_vnpay_refund_api(
        self, payment: PaymentTransaction, amount: Decimal, vnp_request_id: str, reason: str
    ) -> Dict[str, Any]:
        """Format request and compute pipe-separated hash for VNPay refund API."""
        now = datetime.now(VN_TZ)
        create_date = now.strftime("%Y%m%d%H%M%S")
        transaction_date = (
            payment.pay_date.astimezone(VN_TZ).strftime("%Y%m%d%H%M%S")
            if payment.pay_date
            else create_date
        )

        params = {
            "vnp_RequestId": vnp_request_id,
            "vnp_Version": "2.1.0",
            "vnp_Command": "refund",
            "vnp_TmnCode": self.vnp_tmn_code,
            "vnp_TransactionType": "02",  # 02 = hoàn tiền toàn phần
            "vnp_TxnRef": payment.vnp_txn_ref,
            "vnp_Amount": int(amount * 100),
            "vnp_TransactionNo": payment.transaction_no or "0",
            "vnp_TransactionDate": transaction_date,
            "vnp_CreateBy": "system",
            "vnp_CreateDate": create_date,
            "vnp_IpAddr": "127.0.0.1",
            "vnp_OrderInfo": reason,
        }

        # Format pipe-separated hash string in strict required field order
        hash_data = "|".join(
            str(params[k])
            for k in [
                "vnp_RequestId",
                "vnp_Version",
                "vnp_Command",
                "vnp_TmnCode",
                "vnp_TransactionType",
                "vnp_TxnRef",
                "vnp_Amount",
                "vnp_TransactionNo",
                "vnp_TransactionDate",
                "vnp_CreateBy",
                "vnp_CreateDate",
                "vnp_IpAddr",
                "vnp_OrderInfo",
            ]
        )
        secure_hash = hmac.new(
            self.vnp_hash_secret.encode("utf-8"), hash_data.encode("utf-8"), hashlib.sha512
        ).hexdigest()
        params["vnp_SecureHash"] = secure_hash

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(VNPAY_REFUND_URL, json=params)
            resp.raise_for_status()
            return resp.json()

    async def get_refund(self, refund_id: int) -> RefundTransaction:
        """Fetch refund transaction by ID."""
        result = await self.db.execute(
            select(RefundTransaction)
            .where(RefundTransaction.id == refund_id)
            .options(
                selectinload(RefundTransaction.reservation).selectinload(Reservation.user),
                selectinload(RefundTransaction.reservation).selectinload(Reservation.showtime).selectinload(Showtime.movie),
            )
        )
        refund = result.scalar_one_or_none()
        if not refund:
            raise NotFoundException("Yêu cầu hoàn tiền không tồn tại")
        return refund

    async def resolve_refund_manually(
        self, refund_id: int, admin_id: int, admin_note: Optional[str] = None
    ) -> RefundTransaction:
        """Mark refund as resolved manually by admin."""
        refund = await self.get_refund(refund_id)
        refund.status = "success"
        refund.admin_note = admin_note or "Xác nhận hoàn tiền thành công cho khách"
        refund.resolved_by_admin_id = admin_id
        refund.resolved_at = datetime.now(timezone.utc)

        await self.db.flush()
        logger.info("Refund marked resolved manually by admin", refund_id=refund_id, admin_id=admin_id)

        # Trigger success email notification
        await self._trigger_refund_email(refund.id, is_success=True, note_or_reason=refund.admin_note)

        return refund

    async def retry_refund(self, refund_id: int) -> RefundTransaction:
        """Retry calling VNPay refund API for failed or manual_required refund."""
        refund = await self.get_refund(refund_id)
        payment_res = await self.db.execute(
            select(PaymentTransaction).where(PaymentTransaction.id == refund.payment_transaction_id)
        )
        payment = payment_res.scalar_one_or_none()
        if not payment:
            raise NotFoundException("Giao dịch thanh toán gốc không tồn tại")

        refund.status = "processing"
        await self.db.flush()

        try:
            result = await self._call_vnpay_refund_api(
                payment, refund.amount, refund.vnp_request_id, "Thử lại hoàn tiền VNPay"
            )
            response_code = result.get("vnp_ResponseCode")
            if response_code == "00":
                refund.status = "success"
                refund.vnpay_response_message = result.get("vnp_Message") or "Thử lại hoàn tiền tự động thành công"
            else:
                refund.status = "manual_required"
                refund.vnpay_response_message = result.get("vnp_Message") or f"VNPay từ chối (Mã {response_code})"
            refund.vnpay_response_code = response_code
        except Exception as e:
            logger.exception("Retry refund failed", refund_id=refund_id)
            refund.status = "manual_required"
            refund.vnpay_response_message = f"Thử lại thất bại: {str(e)}"

        await self.db.flush()

        # Trigger refund email notification on retry
        is_success = (refund.status == "success")
        note_or_reason = "Xác nhận hoàn tiền thành công cho khách" if is_success else "Không thể hoàn tự động qua VNPAY"
        await self._trigger_refund_email(refund.id, is_success=is_success, note_or_reason=note_or_reason)

        return refund

    async def list_refunds(
        self, status_filter: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List refund transactions for admin view with pagination."""
        query = select(RefundTransaction).options(
            selectinload(RefundTransaction.reservation).selectinload(Reservation.user),
            selectinload(RefundTransaction.reservation).selectinload(Reservation.showtime).selectinload(Showtime.movie),
        )

        if status_filter and status_filter != "all":
            query = query.where(RefundTransaction.status == status_filter)

        count_query = select(func.count(RefundTransaction.id))
        if status_filter and status_filter != "all":
            count_query = count_query.where(RefundTransaction.status == status_filter)

        total_res = await self.db.execute(count_query)
        total = total_res.scalar() or 0

        query = query.order_by(RefundTransaction.id.desc()).offset((page - 1) * page_size).limit(page_size)
        res = await self.db.execute(query)
        refunds = res.scalars().all()

        items = []
        for r in refunds:
            user = r.reservation.user if r.reservation else None
            showtime = r.reservation.showtime if r.reservation else None
            movie_title = showtime.movie.title if showtime and getattr(showtime, "movie", None) else None

            items.append({
                "id": r.id,
                "reservation_id": r.reservation_id,
                "payment_transaction_id": r.payment_transaction_id,
                "amount": r.amount,
                "vnp_request_id": r.vnp_request_id,
                "status": r.status,
                "vnpay_response_code": r.vnpay_response_code,
                "vnpay_response_message": r.vnpay_response_message,
                "admin_note": r.admin_note,
                "resolved_by_admin_id": r.resolved_by_admin_id,
                "resolved_at": r.resolved_at,
                "created_at": r.created_at,
                "ticket_code": r.reservation.ticket_code if r.reservation else None,
                "user_email": user.email if user else None,
                "user_full_name": user.full_name if user else None,
                "movie_title": movie_title,
            })

        return items, total
