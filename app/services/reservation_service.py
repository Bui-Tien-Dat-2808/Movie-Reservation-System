from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    NotFoundException,
    ReservationNotCancellableException,
    SeatUnavailableException,
    ShowtimePastException,
)
from app.models.reservation import Reservation, ReservationSeat, ReservationStatus
from app.models.showtime import Showtime, ShowtimeStatus
from app.models.showtime_seat import ShowtimeSeat, SeatStatus
from app.models.user import User
from app.schemas.reservation import ReservationCreate
from app.services.cache_service import CacheService
from app.utils.datetime_utils import ensure_utc
from app.utils.pagination import PaginationParams

logger = structlog.get_logger()


class ReservationService:
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache

    async def create_reservation(self, user_id: int, data: ReservationCreate) -> Reservation:
        """
        Reserve seats for a showtime.
        Uses SELECT FOR UPDATE to prevent overbooking.
        """
        # Validate showtime
        showtime_result = await self.db.execute(
            select(Showtime).where(Showtime.id == data.showtime_id)
        )
        showtime = showtime_result.scalar_one_or_none()
        if not showtime:
            raise NotFoundException("Showtime", data.showtime_id)

        # Ensure showtime is in the future
        if ensure_utc(showtime.start_time) < datetime.now(timezone.utc):
            raise ShowtimePastException()

        if showtime.status == ShowtimeStatus.CANCELLED:
            raise ShowtimePastException()

        # Lock the requested showtime_seats for update (prevents race conditions)
        locked_seats_result = await self.db.execute(
            select(ShowtimeSeat)
            .where(
                ShowtimeSeat.showtime_id == data.showtime_id,
                ShowtimeSeat.seat_id.in_(data.seat_ids),
            )
            .with_for_update()
        )
        locked_seats = locked_seats_result.scalars().all()

        # Validate seat count
        if len(locked_seats) != len(data.seat_ids):
            missing = set(data.seat_ids) - {s.seat_id for s in locked_seats}
            raise NotFoundException(f"Seats {list(missing)} not found in this showtime")

        # Check if held by this user and not expired
        now = datetime.now(timezone.utc)
        
        for ss in locked_seats:
            if ss.status == SeatStatus.BOOKED:
                raise SeatUnavailableException([ss.seat_id])
            elif ss.status == SeatStatus.HELD:
                held_until_aware = (
                    ss.held_until.replace(tzinfo=timezone.utc)
                    if ss.held_until and ss.held_until.tzinfo is None
                    else (ss.held_until.astimezone(timezone.utc) if ss.held_until else None)
                )
                hold_still_active = held_until_aware and held_until_aware > now
                held_by_someone_else = ss.held_by != user_id
                if hold_still_active and held_by_someone_else:
                    raise SeatUnavailableException([ss.seat_id])

        # Calculate total price (subtotal)
        subtotal = Decimal("0")
        seat_prices = {}

        # Load seats to get types
        from app.models.seat import Seat, SeatType
        for ss in locked_seats:
            seat_result = await self.db.execute(select(Seat).where(Seat.id == ss.seat_id))
            seat = seat_result.scalar_one()
            if seat.seat_type == SeatType.COUPLE:
                price = showtime.couple_price or (showtime.vip_price * Decimal("1.25") if showtime.vip_price else showtime.base_price * Decimal("1.8"))
            elif seat.seat_type == SeatType.VIP and showtime.vip_price:
                price = showtime.vip_price
            elif seat.seat_type == SeatType.KIDS:
                price = showtime.base_price * Decimal("0.85")
            else:
                price = showtime.base_price
            seat_prices[ss.id] = price
            subtotal += price

        # Process voucher discount if provided
        voucher_code = None
        discount_amount = Decimal("0.00")
        final_total = subtotal
        matched_voucher = None

        if data.voucher_code:
            from app.services.voucher_service import VoucherService
            voucher_service = VoucherService(self.db)
            matched_voucher, disc_val, final_val = await voucher_service.validate_and_calculate_discount(
                data.voucher_code, float(subtotal), user_id=user_id
            )
            voucher_code = matched_voucher.code
            discount_amount = Decimal(str(round(disc_val, 2)))
            final_total = Decimal(str(round(final_val, 2)))

        # Cancel any previous PENDING reservations for this user on this showtime to avoid duplicate pending orders
        existing_pending = await self.db.execute(
            select(Reservation).where(
                Reservation.user_id == user_id,
                Reservation.showtime_id == data.showtime_id,
                Reservation.status == ReservationStatus.PENDING,
            )
        )
        for old_res in existing_pending.scalars().all():
            old_res.status = ReservationStatus.CANCELLED
            old_res.notes = "Đã hủy: Thay thế bởi đơn thanh toán mới"
            self.db.add(old_res)

        # Create reservation
        reservation = Reservation(
            user_id=user_id,
            showtime_id=data.showtime_id,
            total_price=final_total,
            voucher_code=voucher_code,
            discount_amount=discount_amount,
            status=ReservationStatus.PENDING,
        )
        self.db.add(reservation)
        await self.db.flush()

        # Record voucher redemption if applicable
        if matched_voucher:
            await voucher_service.record_redemption(
                voucher_id=matched_voucher.id,
                user_id=user_id,
                reservation_id=reservation.id,
            )

        # Create reservation seats and keep showtime_seat HELD for 15 mins during payment
        pay_held_until = now + timedelta(minutes=15)
        for ss in locked_seats:
            ss.status = SeatStatus.HELD
            ss.held_by = user_id
            ss.held_until = pay_held_until
            rs = ReservationSeat(
                reservation_id=reservation.id,
                showtime_seat_id=ss.id,
                price=seat_prices[ss.id],
            )
            self.db.add(rs)

        # Generate unique 6-character random alphanumeric ticket code (e.g. CVN-W1E8KG)
        import secrets, string
        chars = string.ascii_uppercase + string.digits
        rand_code = ''.join(secrets.choice(chars) for _ in range(6))
        reservation.ticket_code = f"CVN-{rand_code}"
        await self.db.flush()

        # Load full reservation with relationships
        result = await self.db.execute(
            select(Reservation)
            .where(Reservation.id == reservation.id)
            .options(
                selectinload(Reservation.reservation_seats)
                .selectinload(ReservationSeat.showtime_seat)
                .selectinload(ShowtimeSeat.seat),
                selectinload(Reservation.showtime)
                .selectinload(Showtime.movie),
                selectinload(Reservation.showtime)
                .selectinload(Showtime.room),
            )
        )
        full_reservation = result.scalar_one()

        # Invalidate seat cache
        await self.cache.delete_pattern(f"showtimes:seats:{data.showtime_id}")

        logger.info(
            "Reservation created",
            reservation_id=reservation.id,
            user_id=user_id,
            total_price=str(final_total),
        )
        return full_reservation

    async def get_user_reservations(
        self, user_id: int, pagination: PaginationParams
    ) -> tuple[List[Reservation], int]:
        """Get reservations for a user."""
        query = select(Reservation).where(Reservation.user_id == user_id)
        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        query = (
            query.offset(pagination.offset)
            .limit(pagination.limit)
            .order_by(Reservation.created_at.desc())
            .options(
                selectinload(Reservation.reservation_seats)
                .selectinload(ReservationSeat.showtime_seat)
                .selectinload(ShowtimeSeat.seat),
                selectinload(Reservation.showtime).selectinload(Showtime.movie),
                selectinload(Reservation.showtime).selectinload(Showtime.room),
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def get_reservation(self, reservation_id: int, user_id: Optional[int] = None) -> Reservation:
        """Get a reservation by ID. If user_id given, enforce ownership."""
        query = (
            select(Reservation)
            .where(Reservation.id == reservation_id)
            .options(
                selectinload(Reservation.reservation_seats)
                .selectinload(ReservationSeat.showtime_seat)
                .selectinload(ShowtimeSeat.seat),
                selectinload(Reservation.showtime).selectinload(Showtime.movie),
                selectinload(Reservation.showtime).selectinload(Showtime.room),
            )
        )
        if user_id:
            query = query.where(Reservation.user_id == user_id)

        result = await self.db.execute(query)
        reservation = result.scalar_one_or_none()
        if not reservation:
            raise NotFoundException("Reservation", reservation_id)
        return reservation

    async def cancel_reservation(
        self, reservation_id: int, user_id: int, reason: Optional[str] = None
    ) -> Reservation:
        """Cancel a reservation (only if showtime is at least 30 minutes in the future)."""
        reservation = await self.get_reservation(reservation_id, user_id)

        if reservation.status == ReservationStatus.CANCELLED:
            raise ReservationNotCancellableException()

        cancel_reason = reason.strip() if (reason and reason.strip()) else "Khách hàng huỷ vé"

        # Check showtime is at least 30 minutes in the future
        showtime = await self.db.get(Showtime, reservation.showtime_id)
        from datetime import datetime, timezone, timedelta
        from app.utils.datetime_utils import ensure_utc
        from app.config import settings

        now = datetime.now(timezone.utc)
        min_mins = getattr(settings, "MIN_MINUTES_BEFORE_CANCEL_OR_EXCHANGE", 30)
        cutoff = ensure_utc(showtime.start_time) - timedelta(minutes=min_mins)

        if now >= cutoff:
            from app.core.exceptions import ValidationException
            raise ValidationException(
                f"Vé chỉ có thể hủy trước giờ chiếu tối thiểu {min_mins} phút."
            )

        # Free up the seats
        for rs in reservation.reservation_seats:
            ss_result = await self.db.execute(
                select(ShowtimeSeat).where(ShowtimeSeat.id == rs.showtime_seat_id)
            )
            ss = ss_result.scalar_one_or_none()
            if ss:
                ss.status = SeatStatus.AVAILABLE
                ss.held_by = None
                ss.held_until = None

        reservation.status = ReservationStatus.CANCELLED
        # Save cancellation reason into reservation notes
        existing_notes = reservation.notes or ""
        reason_note = f"Lý do hủy: {cancel_reason}"
        reservation.notes = f"{existing_notes} | {reason_note}" if (existing_notes and "Lý do hủy:" not in existing_notes) else (reason_note if not existing_notes else existing_notes)
        await self.db.flush()

        # Create refund request if ticket was paid via VNPay or create record for Cash
        from app.models.payment import PaymentTransaction
        payment_result = await self.db.execute(
            select(PaymentTransaction)
            .where(
                PaymentTransaction.reservation_id == reservation.id,
                PaymentTransaction.status == "success",
            )
            .order_by(PaymentTransaction.id.desc())
        )
        payment = payment_result.scalar_one_or_none()

        if payment and payment.payment_method == "vnpay":
            from app.services.refund_service import RefundService
            refund_service = RefundService(self.db)
            try:
                await refund_service.initiate_refund(payment, reason=cancel_reason)
            except Exception:
                logger.exception(
                    "Không thể khởi tạo hoàn tiền tự động cho reservation_id=%s — cần xử lý thủ công",
                    reservation.id,
                )
        else:
            # For Cash payments: create a RefundTransaction record for admin tracking
            if payment and payment.payment_method == "cash":
                try:
                    from app.models.refund import RefundTransaction
                    cash_refund = RefundTransaction(
                        reservation_id=reservation.id,
                        payment_transaction_id=payment.id,
                        amount=reservation.total_price or payment.amount,
                        vnp_request_id=f"CASH_{reservation.id}_{int(datetime.now().timestamp())}",
                        status="success",
                        vnpay_response_message=f"Vé thanh toán Tiền mặt - {cancel_reason}",
                        admin_note=f"Lý do hủy: {cancel_reason}",
                    )
                    self.db.add(cash_refund)
                    await self.db.flush()
                except Exception as e:
                    logger.warning("Failed to create cash refund transaction record", reservation_id=reservation.id, error=str(e))

            # Cash ticket cancellation email notification (thread-safe)
            try:
                user_res = await self.db.execute(select(User).where(User.id == reservation.user_id))
                user_obj = user_res.scalar_one_or_none()
                if user_obj and user_obj.email:
                    movie_title = (
                        reservation.showtime.movie.title
                        if reservation.showtime and getattr(reservation.showtime, "movie", None)
                        else "Phim CineVerse"
                    )
                    ticket_code = reservation.ticket_code or f"CVN-{reservation.id}"
                    amount = reservation.total_price

                    import asyncio
                    from app.services.email_service import EmailService
                    from app.utils.background import fire_and_forget
                    fire_and_forget(
                        asyncio.to_thread(
                            EmailService.send_cash_cancellation_email,
                            user_obj.email,
                            ticket_code,
                            movie_title,
                            amount,
                            cancel_reason,
                        )
                    )
            except Exception as e:
                logger.warning("cash_cancel_email_trigger_failed", reservation_id=reservation.id, error=str(e))

        await self.db.flush()

        # Revoke loyalty points for cancelled booking
        from app.services.loyalty_service import LoyaltyService
        await LoyaltyService.revoke_points(self.db, reservation)

        # Release user from Virtual Queue active set
        try:
            from app.services.queue_service import QueueService
            queue_svc = QueueService(self.cache.redis)
            await queue_svc.leave_queue(reservation.showtime_id, user_id)
        except Exception as e:
            logger.warning("Failed to release queue slot after reservation cancelled", error=str(e))

        await self.cache.delete_pattern(f"showtimes:seats:{reservation.showtime_id}")
        logger.info("Reservation cancelled", reservation_id=reservation_id, user_id=user_id)
        return reservation

    async def exchange_reservation(
        self, reservation_id: int, user_id: int, data
    ) -> Reservation:
        """Exchange an existing confirmed reservation for a new showtime & seats."""
        old_reservation = await self.get_reservation(reservation_id, user_id=user_id)
        if old_reservation.status != ReservationStatus.CONFIRMED:
            from app.core.exceptions import ValidationException
            raise ValidationException("Only CONFIRMED reservations can be exchanged.")

        # Check time limit before old showtime start (at least 30 mins)
        from datetime import datetime, timezone, timedelta
        from app.utils.datetime_utils import ensure_utc
        from app.config import settings
        now = datetime.now(timezone.utc)
        min_mins = getattr(settings, "MIN_MINUTES_BEFORE_CANCEL_OR_EXCHANGE", 30)
        cutoff = old_reservation.showtime.start_time - timedelta(minutes=min_mins)

        if ensure_utc(now) >= ensure_utc(cutoff):
            from app.core.exceptions import ValidationException
            raise ValidationException(
                f"Vé chỉ có thể đổi sang suất khác trước giờ chiếu tối thiểu {min_mins} phút."
            )

        # Create new reservation (PENDING)
        from app.schemas.reservation import ReservationCreate
        new_res_create = ReservationCreate(
            showtime_id=data.new_showtime_id,
            seat_ids=data.new_seat_ids,
            voucher_code=old_reservation.voucher_code,
        )

        new_reservation = await self.create_reservation(user_id=user_id, data=new_res_create)

        # Record link to old reservation — old reservation stays CONFIRMED until new reservation payment succeeds
        new_reservation.exchanged_from_reservation_id = old_reservation.id
        self.db.add(new_reservation)
        await self.db.flush()

        logger.info(
            "Reservation exchange initiated",
            old_reservation_id=reservation_id,
            new_reservation_id=new_reservation.id,
            user_id=user_id,
        )
        return new_reservation

    async def get_all_reservations(
        self, pagination: PaginationParams
    ) -> tuple[List[Reservation], int]:
        """Admin: get all reservations."""
        query = select(Reservation)
        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()

        query = (
            query.offset(pagination.offset)
            .limit(pagination.limit)
            .order_by(Reservation.created_at.desc())
            .options(
                selectinload(Reservation.reservation_seats)
                .selectinload(ReservationSeat.showtime_seat)
                .selectinload(ShowtimeSeat.seat),
                selectinload(Reservation.showtime).selectinload(Showtime.movie),
                selectinload(Reservation.showtime).selectinload(Showtime.room),
                selectinload(Reservation.user),
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def get_revenue_report(self) -> dict:
        """Admin: revenue report."""
        result = await self.db.execute(
            select(
                func.count(Reservation.id).label("total_reservations"),
                func.sum(
                    Reservation.total_price
                ).filter(Reservation.status == ReservationStatus.CONFIRMED).label("total_revenue"),
                func.count(Reservation.id)
                .filter(Reservation.status == ReservationStatus.CONFIRMED)
                .label("confirmed_reservations"),
                func.count(Reservation.id)
                .filter(Reservation.status == ReservationStatus.CANCELLED)
                .label("cancelled_reservations"),
            )
        )
        row = result.one()

        total_revenue = row.total_revenue or Decimal("0")
        confirmed = row.confirmed_reservations or 0
        avg_revenue = total_revenue / confirmed if confirmed > 0 else Decimal("0")

        return {
            "total_revenue": total_revenue,
            "total_reservations": row.total_reservations or 0,
            "confirmed_reservations": confirmed,
            "cancelled_reservations": row.cancelled_reservations or 0,
            "average_revenue_per_reservation": round(avg_revenue, 2),
        }

    async def get_capacity_report(self, pagination: Optional[PaginationParams] = None) -> List[dict]:
        """Admin: per-showtime capacity and revenue report."""
        query = (
            select(Showtime)
            .options(
                selectinload(Showtime.movie),
                selectinload(Showtime.room),
                selectinload(Showtime.showtime_seats),
                selectinload(Showtime.reservations).selectinload(
                    Reservation.reservation_seats
                ),
            )
            .order_by(Showtime.start_time.desc())
        )
        if pagination:
            query = query.offset(pagination.offset).limit(pagination.limit)
        else:
            query = query.limit(50)

        result = await self.db.execute(query)
        showtimes = result.scalars().all()

        report = []
        for st in showtimes:
            total_seats = len(st.showtime_seats)
            reserved_seats = sum(
                1 for s in st.showtime_seats if s.status == SeatStatus.BOOKED
            )
            available_seats = total_seats - reserved_seats
            occupancy_rate = (reserved_seats / total_seats * 100) if total_seats > 0 else 0
            revenue = sum(
                r.total_price for r in st.reservations
                if r.status == ReservationStatus.CONFIRMED
            )

            report.append({
                "showtime_id": st.id,
                "movie_title": st.movie.title if st.movie else "Unknown",
                "room_name": st.room.name if st.room else "Unknown",
                "start_time": st.start_time,
                "total_seats": total_seats,
                "reserved_seats": reserved_seats,
                "available_seats": available_seats,
                "occupancy_rate": round(occupancy_rate, 2),
                "revenue": revenue or Decimal("0"),
            })

        return report

    async def get_reservation_by_code(self, ticket_code: str) -> Optional[Reservation]:
        """Fetch reservation by ticket code with full relationships loaded."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(Reservation)
            .where(Reservation.ticket_code == ticket_code.strip())
            .options(
                selectinload(Reservation.user),
                selectinload(Reservation.showtime).selectinload(Showtime.movie),
                selectinload(Reservation.showtime).selectinload(Showtime.room),
                selectinload(Reservation.reservation_seats).selectinload(ReservationSeat.showtime_seat).selectinload(ShowtimeSeat.seat),
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def verify_ticket(self, ticket_code: str) -> dict:
        """Verify ticket validity for staff scanner."""
        reservation = await self.get_reservation_by_code(ticket_code)
        if not reservation:
            return {"valid": False, "status_code": "NOT_FOUND", "message": f"Mã vé '{ticket_code}' không tồn tại trên hệ thống!"}

        if reservation.status == ReservationStatus.CANCELLED:
            return {
                "valid": False,
                "status_code": "CANCELLED",
                "message": "Vé này đã bị HỦY trước đó!",
                "reservation": ReservationResponse.model_validate(reservation),
            }

        if reservation.is_used:
            return {
                "valid": False,
                "status_code": "CHECKED_IN",
                "message": f"Vé này ĐÃ ĐƯỢC QUÉT VÀO RẠP lúc {reservation.checked_in_at.strftime('%H:%M %d/%m/%Y') if reservation.checked_in_at else 'N/A'}!",
                "reservation": ReservationResponse.model_validate(reservation),
            }

        return {
            "valid": True,
            "status_code": "VALID",
            "message": "Vé HỢP LỆ! Sẵn sàng check-in cho khán giả.",
            "reservation": ReservationResponse.model_validate(reservation),
        }

    async def check_in_ticket(self, ticket_code: str) -> dict:
        """Mark a ticket as checked in (is_used = True)."""
        reservation = await self.get_reservation_by_code(ticket_code)
        if not reservation:
            raise NotFoundException(f"Vé với mã '{ticket_code}' không tồn tại.")

        if reservation.status == ReservationStatus.CANCELLED:
            raise ValidationException("Vé này đã bị hủy, không thể check-in vào rạp.")

        if reservation.is_used:
            raise ValidationException(f"Vé này đã được quét check-in từ trước vào lúc {reservation.checked_in_at.strftime('%H:%M %d/%m/%Y') if reservation.checked_in_at else ''}.")

        reservation.is_used = True
        reservation.checked_in_at = datetime.now(timezone.utc)
        self.db.add(reservation)
        await self.db.commit()
        await self.db.refresh(reservation)

        return {
            "success": True,
            "message": "✅ Check-in vé thành công! Khán giả đã vào rạp.",
            "reservation": ReservationResponse.model_validate(reservation),
        }

    async def confirm_payment_success(
        self, reservation_id: int, vnp_params: Optional[dict] = None, payment_method: str = "vnpay"
    ) -> Reservation:
        """
        Transition reservation from PENDING -> CONFIRMED, mark seats as BOOKED,
        and log PaymentTransaction.
        """
        vnp_params = vnp_params or {}
        reservation = await self.get_reservation(reservation_id)
        if not reservation:
            raise NotFoundException(f"Reservation {reservation_id} not found")

        if reservation.status == ReservationStatus.CONFIRMED:
            return reservation  # Already confirmed (e.g., IPN vs Return callback race)

        # 1. Update Reservation status
        reservation.status = ReservationStatus.CONFIRMED
        self.db.add(reservation)

        # If this reservation was created from an exchange, finalize old reservation now that new payment succeeded
        if getattr(reservation, "exchanged_from_reservation_id", None):
            old_res_result = await self.db.execute(
                select(Reservation)
                .options(selectinload(Reservation.reservation_seats))
                .where(Reservation.id == reservation.exchanged_from_reservation_id)
            )
            old_reservation = old_res_result.scalar_one_or_none()
            if old_reservation and old_reservation.status == ReservationStatus.CONFIRMED:
                for rs in old_reservation.reservation_seats:
                    ss_result = await self.db.execute(
                        select(ShowtimeSeat).where(ShowtimeSeat.id == rs.showtime_seat_id)
                    )
                    ss = ss_result.scalar_one_or_none()
                    if ss:
                        ss.status = SeatStatus.AVAILABLE
                        self.db.add(ss)
                old_reservation.status = ReservationStatus.EXCHANGED
                old_reservation.notes = f"Exchanged to reservation ID {reservation.id}"
                self.db.add(old_reservation)
                await self.cache.delete_pattern(f"showtimes:seats:{old_reservation.showtime_id}")

        # 2. Lock & update ShowtimeSeats from HELD -> BOOKED
        rs_result = await self.db.execute(
            select(ReservationSeat).where(ReservationSeat.reservation_id == reservation.id)
        )
        r_seats = rs_result.scalars().all()
        seat_ids = [rs.showtime_seat_id for rs in r_seats]

        if seat_ids:
            st_seats_result = await self.db.execute(
                select(ShowtimeSeat).where(ShowtimeSeat.id.in_(seat_ids))
            )
            for ss in st_seats_result.scalars().all():
                ss.status = SeatStatus.BOOKED
                ss.held_by = None
                ss.held_until = None
                self.db.add(ss)

        # 3. Add or update PaymentTransaction
        from app.models.payment import PaymentTransaction
        vnp_txn_ref = vnp_params.get("vnp_TxnRef", f"RES_{reservation.id}")
        bank_code = "CASH" if payment_method == "cash" else vnp_params.get("vnp_BankCode")
        card_type = "CASH" if payment_method == "cash" else vnp_params.get("vnp_CardType")

        existing_tx_result = await self.db.execute(
            select(PaymentTransaction).where(PaymentTransaction.vnp_txn_ref == vnp_txn_ref)
        )
        existing_tx = existing_tx_result.scalar_one_or_none()

        if existing_tx:
            existing_tx.status = "success"
            existing_tx.payment_method = payment_method
            existing_tx.transaction_no = vnp_params.get("vnp_TransactionNo", "CASH")
            existing_tx.bank_code = bank_code
            existing_tx.card_type = card_type
            existing_tx.response_code = vnp_params.get("vnp_ResponseCode", "00")
            existing_tx.pay_date = datetime.now(timezone.utc)
            self.db.add(existing_tx)
        else:
            tx = PaymentTransaction(
                reservation_id=reservation.id,
                amount=reservation.total_price,
                payment_method=payment_method,
                vnp_txn_ref=vnp_txn_ref,
                transaction_no=vnp_params.get("vnp_TransactionNo", "CASH"),
                bank_code=bank_code,
                card_type=card_type,
                response_code=vnp_params.get("vnp_ResponseCode", "00"),
                status="success",
                pay_date=datetime.now(timezone.utc),
            )
            self.db.add(tx)

        # 4. Award loyalty points to user (only upon confirmed payment)
        from app.services.loyalty_service import LoyaltyService
        await LoyaltyService.award_points(self.db, reservation)

        # Release user from Virtual Queue active set now that booking is fully completed
        try:
            from app.services.queue_service import QueueService
            queue_svc = QueueService(self.cache.redis)
            await queue_svc.leave_queue(reservation.showtime_id, reservation.user_id)
        except Exception as e:
            logger.warning("Failed to release queue slot after payment confirmed", error=str(e))

        await self.db.commit()
        await self.db.refresh(reservation)

        # 5. Dispatch Automated Ticket Email with Barcode (Thread-safe)
        try:
            user_res = await self.db.execute(select(User).where(User.id == reservation.user_id))
            user_obj = user_res.scalar_one_or_none()
            if user_obj and user_obj.email:
                full_res = await self.get_reservation(reservation.id)
                ticket_code = full_res.ticket_code or f"#{full_res.id}"
                from app.services.email_service import EmailService
                html_content = EmailService.build_ticket_email_html(full_res)
                barcode_bytes = EmailService.generate_barcode_bytes(ticket_code)

                import asyncio
                from app.utils.background import fire_and_forget
                fire_and_forget(
                    asyncio.to_thread(
                        EmailService.send_ticket_email_raw,
                        user_obj.email,
                        ticket_code,
                        html_content,
                        barcode_bytes,
                    )
                )
        except Exception as e:
            logger.warning("email_dispatch_trigger_failed", reservation_id=reservation.id, error=str(e))

        return reservation

    async def cancel_pending_reservation(
        self, reservation_id: int, vnp_params: Optional[dict] = None, reason: str = "Thanh toán thất bại hoặc quá hạn"
    ) -> Reservation:
        """
        Transition reservation from PENDING -> CANCELLED, release seats to AVAILABLE,
        and log failed PaymentTransaction.
        """
        reservation = await self.get_reservation(reservation_id)
        if not reservation:
            raise NotFoundException(f"Reservation {reservation_id} not found")

        if reservation.status == ReservationStatus.CONFIRMED:
            return reservation  # Cannot cancel an already confirmed payment

        reservation.status = ReservationStatus.CANCELLED
        reservation.notes = f"Đã hủy: {reason}"
        self.db.add(reservation)

        # Release seats
        rs_result = await self.db.execute(
            select(ReservationSeat).where(ReservationSeat.reservation_id == reservation.id)
        )
        r_seats = rs_result.scalars().all()
        seat_ids = [rs.showtime_seat_id for rs in r_seats]

        if seat_ids:
            st_seats_result = await self.db.execute(
                select(ShowtimeSeat).where(ShowtimeSeat.id.in_(seat_ids))
            )
            for ss in st_seats_result.scalars().all():
                if ss.status != SeatStatus.BOOKED:
                    ss.status = SeatStatus.AVAILABLE
                    ss.held_by = None
                    ss.held_until = None
                    self.db.add(ss)

        # Record failed transaction if vnp_params provided
        if vnp_params:
            from app.models.payment import PaymentTransaction
            vnp_txn_ref = vnp_params.get("vnp_TxnRef", f"RES_{reservation.id}")
            tx = PaymentTransaction(
                reservation_id=reservation.id,
                amount=reservation.total_price,
                payment_method="vnpay",
                vnp_txn_ref=vnp_txn_ref,
                transaction_no=vnp_params.get("vnp_TransactionNo"),
                bank_code=vnp_params.get("vnp_BankCode"),
                card_type=vnp_params.get("vnp_CardType"),
                response_code=vnp_params.get("vnp_ResponseCode", "99"),
                status="failed",
                pay_date=datetime.now(timezone.utc),
            )
            self.db.add(tx)

        # Release user from Virtual Queue active set now that pending reservation is cancelled/expired
        try:
            from app.services.queue_service import QueueService
            queue_svc = QueueService(self.cache.redis)
            await queue_svc.leave_queue(reservation.showtime_id, reservation.user_id)
        except Exception as e:
            logger.warning("Failed to release queue slot after pending reservation cancelled", error=str(e))

        await self.db.commit()
        await self.db.refresh(reservation)
        return reservation

    async def cleanup_expired_pending_reservations(self) -> int:
        """
        Cancel all PENDING reservations that have passed their 15-minute hold window.
        Returns the number of cancelled reservations.
        """
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(minutes=15)

        result = await self.db.execute(
            select(Reservation).where(
                Reservation.status == ReservationStatus.PENDING,
                Reservation.created_at <= cutoff_time,
            )
        )
        expired_reservations = result.scalars().all()
        count = 0

        for res in expired_reservations:
            try:
                await self.cancel_pending_reservation(res.id, reason="Quá hạn thanh toán 15 phút")
                count += 1
            except Exception as e:
                logger.error("cleanup_pending_reservation_failed", reservation_id=res.id, error=str(e))

        return count
