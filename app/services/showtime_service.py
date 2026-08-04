from datetime import datetime, timezone
from typing import List, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.movie import Movie, MovieGenre, MovieStatus
from app.models.seat import Seat
from app.models.showtime import Showtime, ShowtimeStatus
from app.models.showtime_seat import ShowtimeSeat, SeatStatus
from app.models.room import Room
from app.schemas.showtime import ShowtimeCreate, ShowtimeUpdate
from app.services.cache_service import CacheService
from app.utils.pagination import PaginationParams

logger = structlog.get_logger()


class ShowtimeService:
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache

    def _apply_lazy_expiration(self, showtime_seats: List[ShowtimeSeat]) -> None:
        """Dynamically update held seat status in memory if they have expired."""
        now = datetime.now(timezone.utc)
        for ss in showtime_seats:
            if ss.status == SeatStatus.HELD and ss.held_until:
                held_until_aware = (
                    ss.held_until.replace(tzinfo=timezone.utc) if ss.held_until.tzinfo is None
                    else ss.held_until.astimezone(timezone.utc)
                )
                if held_until_aware < now:
                    ss.status = SeatStatus.AVAILABLE
                    ss.held_by = None
                    ss.held_until = None

    async def _update_showtime_status_if_needed(self, showtime: Showtime) -> None:
        """Dynamically transition showtime status (SCHEDULED -> ONGOING -> COMPLETED) based on current time."""
        if showtime.status == ShowtimeStatus.CANCELLED:
            return

        now = datetime.now(timezone.utc)
        start = (
            showtime.start_time.replace(tzinfo=timezone.utc)
            if showtime.start_time.tzinfo is None
            else showtime.start_time.astimezone(timezone.utc)
        )
        end = (
            showtime.end_time.replace(tzinfo=timezone.utc)
            if showtime.end_time.tzinfo is None
            else showtime.end_time.astimezone(timezone.utc)
        )

        new_status = None
        if now >= end:
            if showtime.status != ShowtimeStatus.COMPLETED:
                new_status = ShowtimeStatus.COMPLETED
        elif now >= start:
            if showtime.status == ShowtimeStatus.SCHEDULED:
                new_status = ShowtimeStatus.ONGOING

        if new_status:
            showtime.status = new_status
            self.db.add(showtime)
            await self.db.flush()

    async def get_showtimes(
        self,
        pagination: PaginationParams,
        movie_id: Optional[int] = None,
        room_id: Optional[int] = None,
        date: Optional[str] = None,
    ) -> tuple[List[Showtime], int]:
        """List showtimes with optional filters."""
        query = select(Showtime).where(Showtime.status != ShowtimeStatus.CANCELLED)

        if movie_id:
            query = query.where(Showtime.movie_id == movie_id)
        if room_id:
            query = query.where(Showtime.room_id == room_id)
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
                query = query.where(func.date(Showtime.start_time) == target_date)
            except ValueError:
                raise ValidationException("Invalid date format. Use YYYY-MM-DD")

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = (
            query.offset(pagination.offset)
            .limit(pagination.limit)
            .order_by(Showtime.start_time)
            .options(
                selectinload(Showtime.movie).selectinload(Movie.movie_genres).selectinload(MovieGenre.genre),
                selectinload(Showtime.room).selectinload(Room.seats),
                selectinload(Showtime.showtime_seats),
            )
        )
        result = await self.db.execute(query)
        showtimes = result.scalars().all()
        
        for st in showtimes:
            self._apply_lazy_expiration(st.showtime_seats)
            await self._update_showtime_status_if_needed(st)

        return list(showtimes), total

    async def get_showtime(self, showtime_id: int) -> Showtime:
        """Get single showtime."""
        result = await self.db.execute(
            select(Showtime)
            .where(Showtime.id == showtime_id)
            .options(
                selectinload(Showtime.movie).selectinload(Movie.movie_genres).selectinload(MovieGenre.genre),
                selectinload(Showtime.room).selectinload(Room.seats),
                selectinload(Showtime.showtime_seats).selectinload(ShowtimeSeat.seat),
            )
        )
        showtime = result.scalar_one_or_none()
        if not showtime:
            raise NotFoundException("Showtime", showtime_id)
        
        self._apply_lazy_expiration(showtime.showtime_seats)
        await self._update_showtime_status_if_needed(showtime)
        return showtime

    async def create_showtime(self, data: ShowtimeCreate) -> Showtime:
        """Create showtime and generate seat slots."""
        # Validate movie exists and is active
        movie = await self.db.get(Movie, data.movie_id)
        if not movie or not movie.is_active:
            raise NotFoundException("Movie", data.movie_id)

        # Only allow showtimes for movies that are currently showing
        if movie.status != MovieStatus.NOW_SHOWING:
            raise ValidationException(
                f"Cannot create a showtime for this movie. "
                f"Movie status is '{movie.status.value}' — only 'now_showing' movies are allowed."
            )

        # Validate start_time is not in the past
        now_utc = datetime.now(timezone.utc)
        st_start = (
            data.start_time.replace(tzinfo=timezone.utc)
            if data.start_time.tzinfo is None
            else data.start_time.astimezone(timezone.utc)
        )
        if st_start < now_utc:
            raise ValidationException("Cannot create a showtime with start_time in the past")

        # Validate room exists
        room_result = await self.db.execute(
            select(Room)
            .where(Room.id == data.room_id)
            .options(selectinload(Room.seats))
        )
        room = room_result.scalar_one_or_none()
        if not room or not room.is_active:
            raise NotFoundException("Room", data.room_id)

        # Check for time conflicts in same room
        conflict = await self.db.execute(
            select(Showtime).where(
                Showtime.room_id == data.room_id,
                Showtime.status != ShowtimeStatus.CANCELLED,
                Showtime.start_time < data.end_time,
                Showtime.end_time > data.start_time,
            )
        )
        if conflict.scalar_one_or_none():
            raise ConflictException(
                "Room already has a showtime scheduled during this time slot"
            )

        # Create showtime
        showtime = Showtime(
            movie_id=data.movie_id,
            room_id=data.room_id,
            start_time=data.start_time,
            end_time=data.end_time,
            base_price=data.base_price,
            vip_price=data.vip_price or data.base_price,
            status=ShowtimeStatus.SCHEDULED,
        )
        self.db.add(showtime)
        await self.db.flush()

        # Generate showtime_seats for all active seats in room
        for seat in room.seats:
            if seat.is_active:
                ss = ShowtimeSeat(
                    showtime_id=showtime.id,
                    seat_id=seat.id,
                    status=SeatStatus.AVAILABLE,
                )
                self.db.add(ss)

        await self.db.flush()
        await self.db.refresh(showtime)
        await self.cache.delete_pattern("showtimes:*")
        logger.info("Showtime created", showtime_id=showtime.id)
        return await self.get_showtime(showtime.id)

    async def update_showtime(self, showtime_id: int, data: ShowtimeUpdate) -> Showtime:
        """Update showtime."""
        showtime = await self.get_showtime(showtime_id)

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is None and field in {"start_time", "end_time", "base_price", "status"}:
                continue
            setattr(showtime, field, value)

        await self.db.flush()
        await self.db.refresh(showtime)
        await self.cache.delete_pattern("showtimes:*")
        logger.info("Showtime updated", showtime_id=showtime_id)
        return await self.get_showtime(showtime_id)

    async def cancel_showtime(self, showtime_id: int) -> Showtime:
        """Cancel a showtime."""
        showtime = await self.get_showtime(showtime_id)
        showtime.status = ShowtimeStatus.CANCELLED
        await self.db.flush()
        await self.cache.delete_pattern("showtimes:*")
        logger.info("Showtime cancelled", showtime_id=showtime_id)
        return showtime

    async def get_seat_map(self, showtime_id: int) -> dict:
        """Get seat availability map for a showtime."""
        showtime = await self.get_showtime(showtime_id)

        seats = []
        available_count = 0
        reserved_count = 0

        for ss in showtime.showtime_seats:
            if ss.status == SeatStatus.AVAILABLE:
                available_count += 1
            elif ss.status == SeatStatus.BOOKED:
                reserved_count += 1

            seats.append(ss)

        return {
            "showtime_id": showtime_id,
            "total_seats": len(seats),
            "available_seats": available_count,
            "reserved_seats": reserved_count,
            "seats": seats,
        }
