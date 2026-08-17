"""Unit tests for movie business logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
from datetime import date, datetime, timezone, timedelta
from app.models.movie import Movie, MovieStatus


class TestMovieSchema:
    """Test movie Pydantic schema validation."""

    def test_valid_movie_create(self):
        from app.schemas.movie import MovieCreate
        data = MovieCreate(
            title="The Matrix",
            description="A sci-fi classic",
            duration_minutes=136,
            genre_ids=[1, 2],
        )
        assert data.title == "The Matrix"
        assert data.duration_minutes == 136
        assert len(data.genre_ids) == 2

    def test_invalid_duration(self):
        from app.schemas.movie import MovieCreate
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            MovieCreate(title="Test", duration_minutes=-5)

    def test_duration_too_long(self):
        from app.schemas.movie import MovieCreate
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            MovieCreate(title="Test", duration_minutes=700)

    def test_movie_update_partial(self):
        from app.schemas.movie import MovieUpdate
        update = MovieUpdate(title="New Title")
        dumped = update.model_dump(exclude_unset=True)
        assert "title" in dumped
        assert "description" not in dumped


class TestMovieAutoStatusTransition:
    """Test automatic status transitions for movies based on release date and showtimes."""

    @pytest.mark.asyncio
    async def test_coming_soon_to_now_showing_on_release_date(self):
        """Test movie in COMING_SOON with past release_date automatically converts to NOW_SHOWING."""
        from app.services.movie_service import MovieService

        db_mock = AsyncMock()
        cache_mock = AsyncMock()
        service = MovieService(db_mock, cache_mock)

        past_movie = Movie(
            id=1,
            title="Released Movie",
            status=MovieStatus.COMING_SOON,
            release_date=date.today() - timedelta(days=5),
            is_active=True
        )

        fut_result = MagicMock()
        fut_result.scalars().all.return_value = []

        movie_result = MagicMock()
        movie_result.scalars().all.return_value = [past_movie]

        db_mock.execute.side_effect = [fut_result, movie_result]

        await service.auto_update_movie_statuses()

        assert past_movie.status == MovieStatus.NOW_SHOWING

    @pytest.mark.asyncio
    async def test_now_showing_to_ended_when_all_showtimes_past(self):
        """Test movie in NOW_SHOWING with only past showtimes converts to ENDED if released > 120 days ago."""
        from app.services.movie_service import MovieService

        db_mock = AsyncMock()
        cache_mock = AsyncMock()
        service = MovieService(db_mock, cache_mock)

        showing_movie = Movie(
            id=2,
            title="Finished Movie",
            status=MovieStatus.NOW_SHOWING,
            release_date=date.today() - timedelta(days=40),
            is_active=True
        )

        fut_result = MagicMock()
        fut_result.scalars().all.return_value = []  # No future showtimes

        movie_result = MagicMock()
        movie_result.scalars().all.return_value = [showing_movie]

        db_mock.execute.side_effect = [fut_result, movie_result]

        await service.auto_update_movie_statuses()

        assert showing_movie.status == MovieStatus.ENDED

    @pytest.mark.asyncio
    async def test_now_showing_with_no_showtimes_and_old_release_date_converts_to_ended(self):
        """Test NOW_SHOWING movie with 0 showtimes and old release_date (e.g. 3 years ago) converts to ENDED."""
        from app.services.movie_service import MovieService

        db_mock = AsyncMock()
        cache_mock = AsyncMock()
        service = MovieService(db_mock, cache_mock)

        old_movie = Movie(
            id=3,
            title="Spider-Man: No Way Home",
            status=MovieStatus.NOW_SHOWING,
            release_date=date.today() - timedelta(days=365 * 3),
            is_active=True
        )

        fut_result = MagicMock()
        fut_result.scalars().all.return_value = []

        movie_result = MagicMock()
        movie_result.scalars().all.return_value = [old_movie]

        db_mock.execute.side_effect = [fut_result, movie_result]

        await service.auto_update_movie_statuses()

        assert old_movie.status == MovieStatus.ENDED


class TestShowtimeSchema:
    """Test showtime schema validation."""

    def test_end_before_start_raises(self):
        from app.schemas.showtime import ShowtimeCreate
        from datetime import datetime, timezone
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ShowtimeCreate(
                movie_id=1,
                room_id=1,
                start_time=datetime(2030, 1, 1, 20, 0, tzinfo=timezone.utc),
                end_time=datetime(2030, 1, 1, 18, 0, tzinfo=timezone.utc),
                base_price=Decimal("15.00"),
            )

    def test_valid_showtime(self):
        from app.schemas.showtime import ShowtimeCreate
        from datetime import datetime, timezone

        st = ShowtimeCreate(
            movie_id=1,
            room_id=1,
            start_time=datetime(2030, 1, 1, 18, 0, tzinfo=timezone.utc),
            end_time=datetime(2030, 1, 1, 20, 0, tzinfo=timezone.utc),
            base_price=Decimal("15.00"),
        )
        assert st.base_price == Decimal("15.00")


class TestReservationSchema:
    """Test reservation schema validation."""

    def test_empty_seat_ids_raises(self):
        from app.schemas.reservation import ReservationCreate
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ReservationCreate(showtime_id=1, seat_ids=[])

    def test_too_many_seats_raises(self):
        from app.schemas.reservation import ReservationCreate
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ReservationCreate(showtime_id=1, seat_ids=list(range(1, 15)))

    def test_valid_reservation(self):
        from app.schemas.reservation import ReservationCreate
        r = ReservationCreate(showtime_id=1, seat_ids=[1, 2, 3])
        assert len(r.seat_ids) == 3


class TestUserSchema:
    """Test user schema validation."""

    def test_weak_password_raises(self):
        from app.schemas.user import UserCreate
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            UserCreate(
                email="user@test.com",
                full_name="Test User",
                password="weakpass"  # no uppercase, no digit
            )

    def test_valid_user(self):
        from app.schemas.user import UserCreate
        u = UserCreate(
            email="user@test.com",
            full_name="Test User",
            password="StrongPass@1",
        )
        assert u.email == "user@test.com"


class TestInferStatusFromReleaseDate:
    """Test MovieService._infer_status_from_release_date safety and correctness."""

    def test_future_iso_string(self):
        from app.services.movie_service import MovieService
        future_str = (date.today() + timedelta(days=30)).isoformat()
        assert MovieService._infer_status_from_release_date(future_str) == MovieStatus.COMING_SOON

    def test_past_iso_string(self):
        from app.services.movie_service import MovieService
        past_str = (date.today() - timedelta(days=30)).isoformat()
        assert MovieService._infer_status_from_release_date(past_str) == MovieStatus.NOW_SHOWING

    def test_future_date_object(self):
        from app.services.movie_service import MovieService
        future_date = date.today() + timedelta(days=30)
        assert MovieService._infer_status_from_release_date(future_date) == MovieStatus.COMING_SOON

    def test_past_date_object(self):
        from app.services.movie_service import MovieService
        past_date = date.today() - timedelta(days=30)
        assert MovieService._infer_status_from_release_date(past_date) == MovieStatus.NOW_SHOWING

    def test_empty_string(self):
        from app.services.movie_service import MovieService
        assert MovieService._infer_status_from_release_date("") == MovieStatus.NOW_SHOWING

    def test_none(self):
        from app.services.movie_service import MovieService
        assert MovieService._infer_status_from_release_date(None) == MovieStatus.NOW_SHOWING

    def test_invalid_format_string(self):
        from app.services.movie_service import MovieService
        assert MovieService._infer_status_from_release_date("invalid-date-format") == MovieStatus.NOW_SHOWING
        assert MovieService._infer_status_from_release_date("2026/13/45") == MovieStatus.NOW_SHOWING
