from datetime import date, timedelta
from decimal import Decimal
import pytest
from unittest.mock import MagicMock, AsyncMock

from app.models.movie import Movie, MovieGenre, MovieStatus
from app.models.genre import Genre
from app.models.room import Room, RoomType
from app.schemas.showtime import AutoScheduleRequest
from app.services.showtime_service import ShowtimeService


@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    return cache


@pytest.mark.asyncio
async def test_kids_room_safety_guard_rejects_t18_movies(mock_db, mock_cache):
    """Test that Kids rooms produce 0 showtimes when only adult/T18 movies are available."""
    service = ShowtimeService(mock_db, mock_cache)

    # Horror genre
    horror_genre = Genre(id=1, name="Kinh Dị")

    # Adult T18 movie
    adult_movie = Movie(
        id=101,
        title="Evil Dead Rises 18+",
        rating="T18",
        duration_minutes=110,
        status=MovieStatus.NOW_SHOWING,
        is_active=True,
    )
    adult_movie.movie_genres = [MovieGenre(movie_id=101, genre_id=1, genre=horror_genre)]

    # Kids room
    kids_room = Room(id=10, name="Kids Play Room", room_type=RoomType.KIDS, is_active=True)

    # Mock DB returns
    mock_db.execute.side_effect = [
        # movie query result
        MagicMock(scalars=lambda: MagicMock(all=lambda: [adult_movie])),
        # room query result
        MagicMock(scalars=lambda: MagicMock(all=lambda: [kids_room])),
    ]

    start_d_str = (date.today() + timedelta(days=1)).isoformat()
    req = AutoScheduleRequest(
        start_date=start_d_str,
        end_date=start_d_str,
        room_ids=[10],
        movie_ids=[101],
        base_price=Decimal("90000"),
        vip_price=Decimal("120000"),
        smart_genre_matching=True,
        auto_pricing_by_room_type=True,
    )

    proposed = await service.generate_auto_schedule_preview(req)

    # MUST be 0 proposed showtimes for Kids room when only T18 movies are present
    assert len(proposed) == 0


@pytest.mark.asyncio
async def test_kids_room_allows_p_rated_animation_movies(mock_db, mock_cache):
    """Test that Kids room accepts P-rated animation movies."""
    service = ShowtimeService(mock_db, mock_cache)

    # Animation genre
    anim_genre = Genre(id=2, name="Hoạt Hình")

    # Kids safe P movie
    kids_movie = Movie(
        id=102,
        title="Doraemon 2026",
        rating="P",
        duration_minutes=90,
        status=MovieStatus.NOW_SHOWING,
        is_active=True,
    )
    kids_movie.movie_genres = [MovieGenre(movie_id=102, genre_id=2, genre=anim_genre)]

    # Kids room
    kids_room = Room(id=10, name="Kids Play Room", room_type=RoomType.KIDS, is_active=True)

    # Mock DB returns
    mock_db.execute.side_effect = [
        # movie query result
        MagicMock(scalars=lambda: MagicMock(all=lambda: [kids_movie])),
        # room query result
        MagicMock(scalars=lambda: MagicMock(all=lambda: [kids_room])),
    ]

    start_d_str = (date.today() + timedelta(days=1)).isoformat()
    req = AutoScheduleRequest(
        start_date=start_d_str,
        end_date=start_d_str,
        room_ids=[10],
        movie_ids=[102],
        base_price=Decimal("90000"),
        vip_price=Decimal("120000"),
        smart_genre_matching=True,
        auto_pricing_by_room_type=True,
    )

    proposed = await service.generate_auto_schedule_preview(req)

    # MUST generate showtimes for Kids room when safe animation movie is present
    assert len(proposed) > 0
    assert all(item.room_id == 10 for item in proposed)
    assert all(item.movie_id == 102 for item in proposed)


@pytest.mark.asyncio
async def test_multiple_standard_rooms_rotate_movies_consistently(mock_db, mock_cache):
    """Test that multiple standard rooms alternate movie rotation index consistently."""
    service = ShowtimeService(mock_db, mock_cache)

    movie1 = Movie(id=1, title="Movie One", duration_minutes=120, status=MovieStatus.NOW_SHOWING, is_active=True)
    movie1.movie_genres = []
    movie2 = Movie(id=2, title="Movie Two", duration_minutes=120, status=MovieStatus.NOW_SHOWING, is_active=True)
    movie2.movie_genres = []

    room1 = Room(id=1, name="Standard 1", room_type=RoomType.STANDARD, is_active=True)
    room2 = Room(id=2, name="Standard 2", room_type=RoomType.STANDARD, is_active=True)

    mock_db.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [movie1, movie2])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [room1, room2])),
    ]

    start_d_str = (date.today() + timedelta(days=1)).isoformat()
    req = AutoScheduleRequest(
        start_date=start_d_str,
        end_date=start_d_str,
        room_ids=[1, 2],
        movie_ids=[1, 2],
        base_price=Decimal("90000"),
        vip_price=Decimal("120000"),
        start_time_str="10:00",
        end_time_str="14:30",
    )

    proposed = await service.generate_auto_schedule_preview(req)

    room1_movies = [item.movie_id for item in proposed if item.room_id == 1]
    room2_movies = [item.movie_id for item in proposed if item.room_id == 2]

    assert len(room1_movies) > 0
    assert len(room2_movies) > 0

    # Both movies should be scheduled across rooms
    all_scheduled = {item.movie_id for item in proposed}
    assert all_scheduled == {1, 2}
