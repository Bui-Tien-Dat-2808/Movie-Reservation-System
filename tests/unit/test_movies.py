"""Unit tests for movie business logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal


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
            MovieCreate(title="Test", duration_minutes=0)

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
