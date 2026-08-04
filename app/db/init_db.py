import structlog
from sqlalchemy import select, text

from app.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.models.user import User, UserRole

# Import all models so Alembic and Base.metadata can find them
from app.models import movie, genre, room, seat, showtime, showtime_seat, reservation  # noqa: F401

logger = structlog.get_logger()


async def init_db() -> None:
    """Initialize the database: create tables, seed admin, rooms, and movies."""
    async with engine.begin() as conn:
        # Create all tables (only if they don't exist)
        await conn.run_sync(Base.metadata.create_all)

    await _seed_admin()
    await _seed_rooms()
    await _seed_tmdb_movies()
    await _seed_showtimes()
    await _seed_vouchers()
    logger.info("Database initialized successfully")


async def _seed_admin() -> None:
    """Create initial admin user if not exists."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.email == settings.ADMIN_EMAIL)
        )
        existing_admin = result.scalar_one_or_none()

        if existing_admin:
            logger.info("Admin user already exists", email=settings.ADMIN_EMAIL)
            return

        admin = User(
            email=settings.ADMIN_EMAIL,
            hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
            full_name=settings.ADMIN_FULL_NAME,
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        logger.info("Admin user created", email=settings.ADMIN_EMAIL)


async def _seed_rooms() -> None:
    """Seed default screening rooms."""
    from app.models.room import Room, RoomType
    from app.api.v1.rooms import _generate_seats

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Room))
        if result.scalars().first():
            logger.info("Rooms already exist, skipping room seeding")
            return

        rooms_data = [
            {"name": "Room 1 (IMAX)", "room_type": RoomType.IMAX, "total_rows": 8, "total_cols": 12},
            {"name": "Room 2 (3D)", "room_type": RoomType.THREE_D, "total_rows": 6, "total_cols": 10},
            {"name": "Room 3 (Standard)", "room_type": RoomType.STANDARD, "total_rows": 10, "total_cols": 15},
            {"name": "Room 4 (VIP)", "room_type": RoomType.VIP, "total_rows": 4, "total_cols": 8},
        ]

        for r_data in rooms_data:
            r_room = Room(
                name=r_data["name"],
                room_type=r_data["room_type"],
                total_rows=r_data["total_rows"],
                total_cols=r_data["total_cols"],
                is_active=True,
            )
            db.add(r_room)
            await db.flush()
            # Generate seats
            await _generate_seats(db, r_room)
            logger.info("Seeded screening room", name=r_room.name, total_seats=r_data["total_rows"] * r_data["total_cols"])

        await db.commit()
        logger.info("Screening rooms seeded successfully")


async def _seed_tmdb_movies() -> None:
    """Seed popular movies from TMDB API if movies table is empty."""
    from app.models.movie import Movie
    from app.services.tmdb_service import TMDBService
    from app.services.movie_service import MovieService
    from app.services.cache_service import CacheService

    async with AsyncSessionLocal() as db:
        if settings.ENVIRONMENT == "test":
            logger.info("Test environment detected, skipping TMDB seeding on startup")
            return

        # Check if database has any movies
        movie_count_result = await db.execute(select(Movie))
        if movie_count_result.scalars().first():
            logger.info("Database already contains movies, skipping TMDB seeding")
            return

        logger.info("Database has no movies. Fetching popular movies from TMDB API to seed...")
        try:
            tmdb = TMDBService()
            # Mock or initialize a simple cache service without actual redis client for safety during initialization
            movie_service = MovieService(db, CacheService(None))

            # Fetch popular movies (page 1)
            popular = await tmdb.get_popular_movies(page=1)
            results = popular.get("results", [])[:10]  # Seed top 10 movies

            for item in results:
                tmdb_id = item["tmdb_id"]
                try:
                    await movie_service.sync_from_tmdb(tmdb_id)
                    logger.info("Successfully seeded movie from TMDB", tmdb_id=tmdb_id, title=item.get("title"))
                except Exception as e:
                    logger.warning("Failed to sync movie during seeding", tmdb_id=tmdb_id, error=str(e))

            await db.commit()
            logger.info("TMDB Movie seeding completed successfully")
        except Exception as e:
            logger.error("Failed to fetch popular movies from TMDB API", error=str(e))


async def _seed_showtimes() -> None:
    """Seed initial showtimes for existing movies if showtimes table is empty."""
    from datetime import datetime, timedelta, timezone, time
    from decimal import Decimal
    from app.models.movie import Movie, MovieStatus
    from app.models.room import Room
    from app.models.showtime import Showtime, ShowtimeStatus
    from app.models.showtime_seat import ShowtimeSeat, SeatStatus

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Showtime))
        if result.scalars().first():
            logger.info("Showtimes already exist, skipping showtime seeding")
            return

        movies_res = await db.execute(select(Movie).where(Movie.status == MovieStatus.NOW_SHOWING))
        movies = list(movies_res.scalars().all())
        if not movies:
            logger.info("No movies found to create showtimes for")
            return

        rooms_res = await db.execute(select(Room))
        rooms = list(rooms_res.scalars().all())
        if not rooms:
            logger.info("No rooms found to create showtimes in")
            return

        # Template showtime slots (hour, minute, room index, price, type label)
        time_slots = [
            (10, 30, 0, Decimal("150000")), # 10:30 Room 1 (IMAX)
            (13, 15, 1, Decimal("120000")), # 13:15 Room 2 (3D)
            (16, 00, 2, Decimal("85000")),  # 16:00 Room 3 (Standard)
            (19, 30, 0, Decimal("180000")), # 19:30 Room 1 (IMAX)
            (22, 15, 3, Decimal("200000")), # 22:15 Room 4 (VIP)
        ]

        now = datetime.now(timezone.utc)
        count = 0

        # Seed showtimes for today and next 6 days
        for day_offset in range(7):
            show_date = now.date() + timedelta(days=day_offset)

            for idx, movie in enumerate(movies):
                # Distribute slots across movies
                slot_hour, slot_min, room_idx, price = time_slots[(idx + day_offset) % len(time_slots)]
                target_room = rooms[room_idx % len(rooms)]

                start_dt = datetime.combine(show_date, time(hour=slot_hour, minute=slot_min), tzinfo=timezone.utc)
                duration = movie.duration_minutes or 120
                end_dt = start_dt + timedelta(minutes=duration)

                st = Showtime(
                    movie_id=movie.id,
                    room_id=target_room.id,
                    start_time=start_dt,
                    end_time=end_dt,
                    base_price=price,
                    vip_price=price * Decimal("1.25"),
                    status=ShowtimeStatus.SCHEDULED,
                )
                db.add(st)
                await db.flush()

                # Generate seats for showtime
                # Load room seats
                await db.refresh(target_room, attribute_names=["seats"])
                for seat in target_room.seats:
                    if seat.is_active:
                        ss = ShowtimeSeat(
                            showtime_id=st.id,
                            seat_id=seat.id,
                            status=SeatStatus.AVAILABLE,
                        )
                        db.add(ss)
                count += 1

        await db.commit()
        logger.info("Successfully seeded showtimes", total_showtimes=count)


async def _seed_vouchers() -> None:
    """Seed default promotional vouchers."""
    from datetime import date
    from app.models.voucher import Voucher, VoucherDiscountType

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Voucher))
        if res.scalars().first():
            logger.info("Vouchers already seeded in database")
            return

        vouchers = [
            Voucher(
                code="WELCOME10",
                discount_type=VoucherDiscountType.PERCENT,
                discount_value=10.0,
                min_spend=100000.0,
                max_discount=50000.0,
                expiry_date=date(2026, 12, 31),
                valid_weekdays=None,
                is_first_booking_only=False,
                max_uses_total=None,
                max_uses_per_user=1,
                is_active=True,
            ),
            Voucher(
                code="HAPPYWED",
                discount_type=VoucherDiscountType.FIXED,
                discount_value=30000.0,
                min_spend=150000.0,
                max_discount=None,
                expiry_date=date(2026, 12, 31),
                valid_weekdays=[2],  # Wednesday only
                is_first_booking_only=False,
                max_uses_total=None,
                max_uses_per_user=None,
                is_active=True,
            ),
            Voucher(
                code="CINEVERSE10",
                discount_type=VoucherDiscountType.PERCENT,
                discount_value=10.0,
                min_spend=0.0,
                max_discount=100000.0,
                expiry_date=date(2026, 12, 31),
                valid_weekdays=None,
                is_first_booking_only=True,
                max_uses_total=None,
                max_uses_per_user=1,
                is_active=True,
            ),
            Voucher(
                code="VIPMOVIE",
                discount_type=VoucherDiscountType.FIXED,
                discount_value=50000.0,
                min_spend=200000.0,
                max_discount=None,
                expiry_date=date(2026, 12, 31),
                valid_weekdays=None,
                is_first_booking_only=False,
                max_uses_total=500,
                max_uses_per_user=2,
                is_active=True,
            ),
        ]
        db.add_all(vouchers)
        await db.commit()
        logger.info("Default vouchers created", count=len(vouchers))

