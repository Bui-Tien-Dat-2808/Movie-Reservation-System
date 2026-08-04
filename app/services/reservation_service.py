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
        if showtime.start_time.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
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
                and (
                    ss.held_until.replace(tzinfo=timezone.utc) if ss.held_until.tzinfo is None 
                    else ss.held_until.astimezone(timezone.utc)
                ) >= now
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
            if seat.seat_type == SeatType.VIP and showtime.vip_price:
                price = showtime.vip_price
            else:
                price = showtime.base_price
            seat_prices[ss.id] = price
            subtotal += price

        # Process voucher discount if provided
        voucher_code = None
        discount_amount = Decimal("0.00")
        final_total = subtotal

        if data.voucher_code:
            from app.services.voucher_service import VoucherService
            match, disc_val, final_val = VoucherService.validate_and_calculate_discount(
                data.voucher_code, float(subtotal)
            )
            voucher_code = match.code
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
        """Cancel a reservation (only if showtime is upcoming)."""
        reservation = await self.get_reservation(reservation_id, user_id)

        if reservation.status == ReservationStatus.CANCELLED:
            raise ReservationNotCancellableException()

        # Check showtime is in the future
        showtime = await self.db.get(Showtime, reservation.showtime_id)
        if showtime.start_time.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            raise ReservationNotCancellableException()

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

    async def get_capacity_report(self) -> List[dict]:
        """Admin: per-showtime capacity and revenue report."""
        result = await self.db.execute(
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
            .limit(50)
        )
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
