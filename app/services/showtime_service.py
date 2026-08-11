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
from app.models.room import Room, RoomType
from app.schemas.showtime import ShowtimeCreate, ShowtimeUpdate
from app.services.cache_service import CacheService
from app.utils.pagination import PaginationParams
from app.utils.datetime_utils import ensure_utc

logger = structlog.get_logger()


class ShowtimeService:
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache

    def _apply_lazy_expiration(self, showtime_seats: List[ShowtimeSeat]) -> None:
        """Lazily expire seats held past held_until."""
        now = datetime.now(timezone.utc)
        for ss in showtime_seats:
            if ss.status == SeatStatus.HELD and ss.held_until:
                held_until_aware = ensure_utc(ss.held_until)
                if held_until_aware < now:
                    ss.status = SeatStatus.AVAILABLE
                    ss.held_by = None
                    ss.held_until = None

    async def _update_showtime_status_if_needed(self, showtime: Showtime) -> None:
        """Dynamically transition showtime status (SCHEDULED -> ONGOING -> COMPLETED) based on current time."""
        if showtime.status == ShowtimeStatus.CANCELLED:
            return

        now = datetime.now(timezone.utc)
        start = ensure_utc(showtime.start_time)
        end = ensure_utc(showtime.end_time)

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
        upcoming_only: bool = False,
    ) -> tuple[List[dict], int]:
        """List showtimes with optional filters using high performance SQL aggregation."""
        from sqlalchemy import Integer
        from app.schemas.showtime import ShowtimeResponse

        query = select(Showtime).where(Showtime.status != ShowtimeStatus.CANCELLED)

        if upcoming_only:
            now_utc = datetime.now(timezone.utc)
            query = query.where(Showtime.start_time > now_utc)

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
            .order_by(Showtime.start_time.desc())
            .options(
                selectinload(Showtime.movie).selectinload(Movie.movie_genres).selectinload(MovieGenre.genre),
                selectinload(Showtime.room).selectinload(Room.seats),
            )
        )
        result = await self.db.execute(query)
        showtimes = result.scalars().all()
        
        for st in showtimes:
            await self._update_showtime_status_if_needed(st)

        if showtimes:
            from sqlalchemy import case

            st_ids = [st.id for st in showtimes]
            seat_stmt = (
                select(
                    ShowtimeSeat.showtime_id,
                    func.count(ShowtimeSeat.id).label("total_seats"),
                    func.sum(
                        case((ShowtimeSeat.status == SeatStatus.AVAILABLE, 1), else_=0)
                    ).label("available_seats"),
                )
                .where(ShowtimeSeat.showtime_id.in_(st_ids))
                .group_by(ShowtimeSeat.showtime_id)
            )
            seat_res = await self.db.execute(seat_stmt)
            seat_counts = {
                row.showtime_id: (int(row.total_seats or 0), int(row.available_seats or 0))
                for row in seat_res
            }
        else:
            seat_counts = {}

        items = []
        for st in showtimes:
            total_s, avail_s = seat_counts.get(st.id, (0, 0))
            resp = ShowtimeResponse.model_validate(st)
            resp.total_seats = total_s
            resp.available_seats = avail_s
            items.append(resp)

        return items, total

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

        # Allow showtimes for movies that are currently showing or coming soon
        if movie.status not in {MovieStatus.NOW_SHOWING, MovieStatus.COMING_SOON}:
            raise ValidationException(
                f"Cannot create a showtime for this movie. "
                f"Movie status is '{movie.status.value}' — only 'now_showing' or 'coming_soon' movies are allowed."
            )

        # Validate start_time is not in the past
        now_utc = datetime.now(timezone.utc)
        st_start = ensure_utc(data.start_time)
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
            vip_price=data.vip_price,
            status=ShowtimeStatus.SCHEDULED,
        )
        self.db.add(showtime)
        await self.db.flush()

        # Generate showtime_seats
        for seat in room.seats:
            if seat.is_active:
                st_seat = ShowtimeSeat(
                    showtime_id=showtime.id,
                    seat_id=seat.id,
                    status=SeatStatus.AVAILABLE,
                )
                self.db.add(st_seat)

        await self.db.flush()
        await self.db.refresh(showtime)
        await self.cache.delete_pattern("showtimes:*")
        logger.info("Showtime created", showtime_id=showtime.id)
        return await self.get_showtime(showtime.id)

    async def update_showtime(self, showtime_id: int, data: ShowtimeUpdate) -> Showtime:
        """Update showtime with conflict and past-time checks."""
        showtime = await self.get_showtime(showtime_id)

        update_data = data.model_dump(exclude_unset=True)

        if "start_time" in update_data or "end_time" in update_data:
            new_start = update_data.get("start_time", showtime.start_time)
            new_end = update_data.get("end_time", showtime.end_time)

            now_utc = datetime.now(timezone.utc)
            check_start = ensure_utc(new_start)
            if check_start < now_utc:
                raise ValidationException("Cannot move a showtime's start_time into the past")

            conflict = await self.db.execute(
                select(Showtime).where(
                    Showtime.room_id == showtime.room_id,
                    Showtime.id != showtime_id,
                    Showtime.status != ShowtimeStatus.CANCELLED,
                    Showtime.start_time < new_end,
                    Showtime.end_time > new_start,
                )
            )
            if conflict.scalar_one_or_none():
                raise ConflictException("Room already has a showtime scheduled during this time slot")

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

    async def bulk_cancel_showtimes(
        self,
        movie_id: Optional[int] = None,
        room_id: Optional[int] = None,
        only_upcoming: bool = True,
        showtime_ids: Optional[List[int]] = None,
    ) -> int:
        """Bulk cancel showtimes matching optional filters, preserving past/running showtimes by default."""
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)

        query = select(Showtime).where(Showtime.status != ShowtimeStatus.CANCELLED)

        if showtime_ids:
            query = query.where(Showtime.id.in_(showtime_ids))
        if movie_id:
            query = query.where(Showtime.movie_id == movie_id)
        if room_id:
            query = query.where(Showtime.room_id == room_id)
        if only_upcoming:
            # Preserve past and currently playing showtimes
            query = query.where(Showtime.start_time >= now_utc)

        res = await self.db.execute(query)
        showtimes = res.scalars().all()
        count = len(showtimes)

        for st in showtimes:
            st.status = ShowtimeStatus.CANCELLED

        await self.db.commit()
        await self.cache.delete_pattern("showtimes:*")
        logger.info("Bulk showtimes cancelled", count=count, movie_id=movie_id, room_id=room_id, only_upcoming=only_upcoming)
        return count

    async def get_seat_map(self, showtime_id: int) -> dict:
        """Get seat availability map for a showtime, with auto-healing for missing seat slots."""
        showtime = await self.get_showtime(showtime_id)

        # Auto-heal: If showtime has no showtime_seats generated, create them from room seats
        if not showtime.showtime_seats:
            for seat in showtime.room.seats:
                if seat.is_active:
                    st_seat = ShowtimeSeat(
                        showtime_id=showtime.id,
                        seat_id=seat.id,
                        status=SeatStatus.AVAILABLE,
                    )
                    self.db.add(st_seat)
            await self.db.flush()
            await self.db.commit()
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

    async def generate_auto_schedule_preview(
        self, req
    ):
        """Algorithm to generate proposed auto-scheduled showtimes without saving to DB."""
        from datetime import datetime, date as date_cls, time as time_cls, timedelta, timezone
        from app.models.movie import Movie, MovieStatus
        from app.models.room import Room
        from app.schemas.showtime import ProposedShowtimeItem
        from app.core.exceptions import ValidationException

        try:
            start_d = date_cls.fromisoformat(req.start_date)
            end_d = date_cls.fromisoformat(req.end_date)
        except ValueError:
            raise ValidationException("Invalid date format. Use YYYY-MM-DD")

        if end_d < start_d:
            raise ValidationException("end_date must be greater than or equal to start_date")

        from decimal import Decimal
        from app.models.room import RoomType

        ROOM_TYPE_MULTIPLIERS = {
            RoomType.STANDARD: Decimal("1.0"),
            RoomType.KIDS: Decimal("0.9"),
            RoomType.THREE_D: Decimal("1.3"),
            RoomType.FOUR_D: Decimal("1.5"),
            RoomType.IMAX: Decimal("1.7"),
            RoomType.VIP: Decimal("1.8"),
        }

        ROOM_GENRE_AFFINITY = {
            RoomType.IMAX: {"Hành Động", "Viễn Tưởng", "Phiêu Lưu", "Kỳ Ảo", "Action", "Sci-Fi", "Adventure", "Fantasy"},
            RoomType.FOUR_D: {"Hành Động", "Mạo Hiểm", "Kinh Dị", "Đua Xe", "Action", "Horror", "Thriller"},
            RoomType.THREE_D: {"Hoạt Hình", "Viễn Tưởng", "Kỳ Ảo", "Animation", "Sci-Fi", "Fantasy"},
            RoomType.KIDS: {"Hoạt Hình", "Gia Đình", "Thiếu Nhi", "Animation", "Family"},
            RoomType.VIP: {"Tình Cảm", "Tâm Lý", "Hài", "Nghệ Thuật", "Romance", "Drama", "Comedy"},
            RoomType.STANDARD: set(),
        }

        movie_query = (
            select(Movie)
            .where(Movie.is_active == True)
            .options(
                selectinload(Movie.movie_genres).selectinload(MovieGenre.genre)
            )
        )
        if req.movie_ids:
            movie_query = movie_query.where(Movie.id.in_(req.movie_ids))
        else:
            movie_query = movie_query.where(
                Movie.status.in_([MovieStatus.NOW_SHOWING, MovieStatus.COMING_SOON])
            )

        movie_res = await self.db.execute(movie_query)
        movies = movie_res.scalars().all()

        if not movies:
            raise ValidationException("No active movies found for auto-scheduling")

        if req.room_ids:
            room_res = await self.db.execute(
                select(Room).where(Room.id.in_(req.room_ids), Room.is_active == True)
            )
            rooms = room_res.scalars().all()
        else:
            room_res = await self.db.execute(select(Room).where(Room.is_active == True))
            rooms = room_res.scalars().all()

        if not rooms:
            raise ValidationException("No active screening rooms found")

        proposed_list = []
        movie_idx_by_type: dict = {}
        now_utc = datetime.now(timezone.utc)

        from app.utils.datetime_utils import ensure_utc, get_cinema_timezone
        cinema_tz = get_cinema_timezone()

        KIDS_SAFE_RATINGS = {"P", "K", "T13", "G", "PG", "PG-13"}

        curr_d = start_d
        while curr_d <= end_d:
            # Filter candidate movies whose release_date has arrived on or before curr_d
            day_movies = [m for m in movies if not m.release_date or m.release_date <= curr_d]
            if not day_movies:
                day_movies = movies

            for room in rooms:
                # Dynamic Pricing Multiplier
                if getattr(req, "auto_pricing_by_room_type", True):
                    mult = ROOM_TYPE_MULTIPLIERS.get(room.room_type, Decimal("1.0"))
                    calc_base = (req.base_price * mult).quantize(Decimal("1000"))
                    calc_vip = (req.vip_price * mult).quantize(Decimal("1000"))
                else:
                    calc_base = req.base_price
                    calc_vip = req.vip_price

                # Smart Genre Matching & Kids Safety Guard
                affinity_set = ROOM_GENRE_AFFINITY.get(room.room_type, set())

                if room.room_type == RoomType.KIDS:
                    safe_movies = []
                    for movie in day_movies:
                        r = (movie.rating or "").upper().strip()
                        is_safe_rating = not r or r in KIDS_SAFE_RATINGS
                        m_genres = {mg.genre.name for mg in movie.movie_genres if mg.genre}
                        has_kids_genre = bool(m_genres.intersection(affinity_set))
                        if is_safe_rating and has_kids_genre:
                            safe_movies.append(movie)

                    if not safe_movies:
                        # Safety Rule: NEVER fallback to all movies for Kids rooms! Skip room if no kids-safe movies exist.
                        continue

                    effective_movies = safe_movies
                    genre_lookup = {}
                    for m in safe_movies:
                        matched = list({mg.genre.name for mg in m.movie_genres if mg.genre}.intersection(affinity_set))
                        if matched:
                            genre_lookup[m.id] = matched[0]
                else:
                    matched_pairs = []
                    if getattr(req, "smart_genre_matching", True) and affinity_set:
                        for movie in day_movies:
                            m_genres = {mg.genre.name for mg in movie.movie_genres if mg.genre}
                            common = m_genres.intersection(affinity_set)
                            if common:
                                matched_pairs.append((movie, list(common)[0]))

                    if matched_pairs:
                        matched_movies = [p[0] for p in matched_pairs]
                        other_movies = [m for m in day_movies if m not in matched_movies]
                        effective_movies = matched_movies + other_movies
                        genre_lookup = {p[0].id: p[1] for p in matched_pairs}
                    else:
                        effective_movies = day_movies
                        genre_lookup = {}

                # Dynamic Rotation: Offset movie rotation by room index and day offset
                # to guarantee smooth time slot rotation and broad room type coverage across days
                room_idx = rooms.index(room)
                day_offset = (curr_d - start_d).days
                idx_key = f"{room.room_type}_{room.id}"
                base_start_idx = day_offset * 5 + room_idx * 3
                movie_idx = movie_idx_by_type.get(idx_key, base_start_idx)

                start_dt_bound = datetime.combine(curr_d, time_cls(0, 0), tzinfo=cinema_tz).astimezone(timezone.utc)
                end_dt_bound = datetime.combine(curr_d, time_cls(23, 59, 59), tzinfo=cinema_tz).astimezone(timezone.utc)

                if getattr(req, "replace_existing", True):
                    existing_st = []
                else:
                    existing_res = await self.db.execute(
                        select(Showtime).where(
                            Showtime.room_id == room.id,
                            Showtime.status != ShowtimeStatus.CANCELLED,
                            Showtime.start_time >= start_dt_bound,
                            Showtime.start_time <= end_dt_bound,
                        ).order_by(Showtime.start_time.asc())
                    )
                    existing_st = existing_res.scalars().all()

                start_h, start_m = 8, 0
                end_h, end_m = 23, 30

                if getattr(req, "start_time_str", None):
                    parts = req.start_time_str.split(":")
                    if len(parts) == 2:
                        start_h, start_m = int(parts[0]), int(parts[1])
                elif getattr(req, "start_hour", None) is not None:
                    start_h = req.start_hour

                if getattr(req, "end_time_str", None):
                    parts = req.end_time_str.split(":")
                    if len(parts) == 2:
                        end_h, end_m = int(parts[0]), int(parts[1])
                elif getattr(req, "end_hour", None) is not None:
                    end_h = req.end_hour

                day_start_dt = datetime.combine(curr_d, time_cls(start_h, start_m), tzinfo=cinema_tz).astimezone(timezone.utc)
                day_end_dt = datetime.combine(curr_d, time_cls(end_h, end_m), tzinfo=cinema_tz).astimezone(timezone.utc)

                slot_time = day_start_dt

                while slot_time < day_end_dt:
                    if slot_time < now_utc:
                        slot_time += timedelta(minutes=30)
                        continue

                    m = effective_movies[movie_idx % len(effective_movies)]
                    duration_mins = m.duration_minutes or 120
                    st_end = slot_time + timedelta(minutes=duration_mins)

                    has_collision = False
                    for ex in existing_st:
                        ex_start = ensure_utc(ex.start_time)
                        ex_end = ensure_utc(ex.end_time)
                        if slot_time < ex_end and st_end > ex_start:
                            has_collision = True
                            slot_time = ex_end + timedelta(minutes=req.buffer_minutes)
                            break

                    if has_collision:
                        continue

                    if st_end > day_end_dt:
                        break

                    matched_g = genre_lookup.get(m.id)

                    proposed_list.append(
                        ProposedShowtimeItem(
                            movie_id=m.id,
                            movie_title=m.title,
                            room_id=room.id,
                            room_name=room.name,
                            room_type=room.room_type.value if hasattr(room.room_type, "value") else str(room.room_type),
                            matched_genre=matched_g,
                            start_time=slot_time,
                            end_time=st_end,
                            base_price=calc_base,
                            vip_price=calc_vip,
                        )
                    )

                    slot_time = st_end + timedelta(minutes=req.buffer_minutes)
                    movie_idx += 1

                # Persist rotation index for this room type
                movie_idx_by_type[idx_key] = movie_idx

            curr_d += timedelta(days=1)

        return proposed_list

    async def confirm_auto_schedule(
        self,
        showtimes_data: list,
        replace_existing: bool = True,
    ) -> int:
        """Bulk insert approved auto-scheduled showtimes into DB."""
        from app.models.room import Room
        from app.models.showtime_seat import ShowtimeSeat, SeatStatus

        if not showtimes_data:
            return 0

        if replace_existing and showtimes_data:
            all_starts = [ensure_utc(item.start_time) for item in showtimes_data]
            all_ends = [ensure_utc(item.end_time) for item in showtimes_data]
            min_start = min(all_starts)
            max_end = max(all_ends)
            all_room_ids = list({item.room_id for item in showtimes_data})

            clean_stmt = (
                select(Showtime)
                .where(
                    Showtime.room_id.in_(all_room_ids),
                    Showtime.status != ShowtimeStatus.CANCELLED,
                    Showtime.start_time >= min_start,
                    Showtime.start_time <= max_end,
                )
            )
            old_res = await self.db.execute(clean_stmt)
            old_sts = old_res.scalars().all()
            for old_st in old_sts:
                old_st.status = ShowtimeStatus.CANCELLED
            if old_sts:
                await self.db.flush()
                logger.info("Replaced existing showtimes", cancelled_count=len(old_sts))

        count = 0
        for item in showtimes_data:
            st = Showtime(
                movie_id=item.movie_id,
                room_id=item.room_id,
                start_time=ensure_utc(item.start_time),
                end_time=ensure_utc(item.end_time),
                base_price=item.base_price,
                vip_price=item.vip_price,
                status=ShowtimeStatus.SCHEDULED,
            )
            self.db.add(st)
            await self.db.flush()

            room = await self.db.get(Room, item.room_id)
            if room:
                await self.db.refresh(room, attribute_names=["seats"])
                if not room.seats:
                    logger.warning("Screening room has no seats configured", room_id=item.room_id)
                for seat in room.seats:
                    if seat.is_active:
                        ss = ShowtimeSeat(
                            showtime_id=st.id,
                            seat_id=seat.id,
                            status=SeatStatus.AVAILABLE,
                        )
                        self.db.add(ss)
            else:
                logger.warning("Room not found during auto-schedule confirm", room_id=item.room_id)
            count += 1
            logger.info("Auto-scheduled showtime created", showtime_id=st.id, movie_id=st.movie_id, room_id=st.room_id)

        await self.db.commit()
        await self.cache.delete_pattern("showtimes:*")
        logger.info("Auto-scheduled showtimes committed", total=count)
        return count
