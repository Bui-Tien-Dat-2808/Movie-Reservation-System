from datetime import datetime, timezone
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
            is_valid_hold = (
                ss.status == SeatStatus.HELD
                and ss.held_by == user_id
                and ss.held_until is not None
                and ensure_utc(ss.held_until) >= now
            )
            if not is_valid_hold:
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

        # Create reservation
        reservation = Reservation(
            user_id=user_id,
            showtime_id=data.showtime_id,
            total_price=final_total,
            voucher_code=voucher_code,
            discount_amount=discount_amount,
            status=ReservationStatus.CONFIRMED,
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

        # Create reservation seats and update showtime_seat status
        for ss in locked_seats:
            ss.status = SeatStatus.BOOKED
            ss.held_by = None
            ss.held_until = None
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

    async def cancel_reservation(self, reservation_id: int, user_id: int) -> Reservation:
        """Cancel a reservation (only if showtime is at least 30 minutes in the future)."""
        reservation = await self.get_reservation(reservation_id, user_id)

        if reservation.status == ReservationStatus.CANCELLED:
            raise ReservationNotCancellableException()

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

        reservation.status = ReservationStatus.CANCELLED
        await self.db.flush()

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

        # 1. Release old seats
        for rs in old_reservation.reservation_seats:
            ss_result = await self.db.execute(
                select(ShowtimeSeat).where(ShowtimeSeat.id == rs.showtime_seat_id)
            )
            ss = ss_result.scalar_one_or_none()
            if ss:
                ss.status = SeatStatus.AVAILABLE

        # Mark old reservation as EXCHANGED
        old_reservation.status = ReservationStatus.EXCHANGED
        old_reservation.notes = f"Exchanged to new showtime ID {data.new_showtime_id}"
        await self.db.flush()

        await self.cache.delete_pattern(f"showtimes:seats:{old_reservation.showtime_id}")

        # 2. Create new reservation
        from app.schemas.reservation import ReservationCreate
        new_res_create = ReservationCreate(
            showtime_id=data.new_showtime_id,
            seat_ids=data.new_seat_ids,
            voucher_code=old_reservation.voucher_code,
        )

        new_reservation = await self.create_reservation(user_id=user_id, data=new_res_create)

        logger.info(
            "Reservation exchanged successfully",
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
