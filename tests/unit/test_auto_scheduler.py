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


@pytest.mark.asyncio
async def test_a1_future_release_date_skips_day(mock_db, mock_cache):
    """A1 Test: If selected candidate movies all have release_date in the future, return 0 showtimes."""
    service = ShowtimeService(mock_db, mock_cache)

    future_movie = Movie(
        id=201,
        title="Avatar 4 Future",
        duration_minutes=150,
        release_date=date.today() + timedelta(days=10),
        status=MovieStatus.COMING_SOON,
        is_active=True,
    )
    future_movie.movie_genres = []
    std_room = Room(id=1, name="Standard 1", room_type=RoomType.STANDARD, is_active=True, seats=[])

    mock_db.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [future_movie])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [std_room])),
    ]

    target_d = (date.today() + timedelta(days=1)).isoformat()
    req = AutoScheduleRequest(
        start_date=target_d,
        end_date=target_d,
        base_price=Decimal("90000"),
        vip_price=Decimal("120000"),
    )

    proposed = await service.generate_auto_schedule_preview(req)
    assert len(proposed) == 0


@pytest.mark.asyncio
async def test_a2_ended_movie_is_excluded(mock_db, mock_cache):
    """A2 Test: When admin selects specific movie_ids including an ENDED movie, only active NOW_SHOWING/COMING_SOON movies are scheduled."""
    service = ShowtimeService(mock_db, mock_cache)

    active_movie = Movie(id=301, title="Active Movie", duration_minutes=100, status=MovieStatus.NOW_SHOWING, is_active=True)
    active_movie.movie_genres = []
    std_room = Room(id=1, name="Standard 1", room_type=RoomType.STANDARD, is_active=True, seats=[])

    mock_db.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [active_movie])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [std_room])),
    ]

    target_d = (date.today() + timedelta(days=1)).isoformat()
    req = AutoScheduleRequest(
        start_date=target_d,
        end_date=target_d,
        movie_ids=[301, 302],  # 302 is ENDED and filtered out in DB query
        base_price=Decimal("90000"),
        vip_price=Decimal("120000"),
    )

    proposed = await service.generate_auto_schedule_preview(req)
    assert len(proposed) > 0
    assert all(item.movie_id == 301 for item in proposed)


@pytest.mark.asyncio
async def test_b1_weighted_pool_popularity(mock_db, mock_cache):
    """B1 Test: Higher popularity movies appear more frequently in the weighted pool."""
    service = ShowtimeService(mock_db, mock_cache)

    hot_movie = Movie(id=401, title="Hot Movie", popularity=150.0, duration_minutes=90, status=MovieStatus.NOW_SHOWING, is_active=True)
    hot_movie.movie_genres = []
    cold_movie = Movie(id=402, title="Cold Movie", popularity=10.0, duration_minutes=90, status=MovieStatus.NOW_SHOWING, is_active=True)
    cold_movie.movie_genres = []
    std_room = Room(id=1, name="Standard 1", room_type=RoomType.STANDARD, is_active=True, seats=[])

    mock_db.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [hot_movie, cold_movie])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [std_room])),
    ]

    target_d = (date.today() + timedelta(days=1)).isoformat()
    req = AutoScheduleRequest(
        start_date=target_d,
        end_date=target_d,
        start_time_str="08:00",
        end_time_str="22:00",
        base_price=Decimal("100000"),
        vip_price=Decimal("120000"),
    )

    proposed = await service.generate_auto_schedule_preview(req)
    hot_count = sum(1 for item in proposed if item.movie_id == 401)
    cold_count = sum(1 for item in proposed if item.movie_id == 402)

    assert hot_count > cold_count


@pytest.mark.asyncio
async def test_b2_dayparting_movie_assignment_and_pricing(mock_db, mock_cache):
    """B2 Test: Peak time (>=18h) applies 1.15x pricing multiplier and off-peak (<12h) applies 0.85x pricing multiplier."""
    service = ShowtimeService(mock_db, mock_cache)

    movie = Movie(id=501, title="Sample Movie", popularity=50.0, duration_minutes=120, status=MovieStatus.NOW_SHOWING, is_active=True)
    movie.movie_genres = []
    std_room = Room(id=1, name="Standard 1", room_type=RoomType.STANDARD, is_active=True, seats=[])

    mock_db.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [movie])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [std_room])),
    ]

    # Use a Wednesday (weekday) to isolate dayparting pricing without weekend multiplier
    wednesday_d = date.today() + timedelta(days=(2 - date.today().weekday()) % 7)
    if wednesday_d <= date.today():
        wednesday_d += timedelta(days=7)

    req = AutoScheduleRequest(
        start_date=wednesday_d.isoformat(),
        end_date=wednesday_d.isoformat(),
        start_time_str="09:00",
        end_time_str="21:00",
        base_price=Decimal("100000"),
        vip_price=Decimal("120000"),
        auto_pricing_by_room_type=False,
    )

    proposed = await service.generate_auto_schedule_preview(req)

    from app.utils.datetime_utils import get_cinema_timezone
    cinema_tz = get_cinema_timezone()

    # 9:00 AM (off_peak < 12h) -> 100000 * 0.85 = 85000
    off_peak_items = [item for item in proposed if item.start_time.astimezone(cinema_tz).hour < 12]
    assert len(off_peak_items) > 0
    assert off_peak_items[0].base_price == Decimal("85000")

    # 18:00+ (peak >= 18h) -> 100000 * 1.15 = 115000
    peak_items = [item for item in proposed if item.start_time.astimezone(cinema_tz).hour >= 18]
    assert len(peak_items) > 0
    assert peak_items[0].base_price == Decimal("115000")


@pytest.mark.asyncio
async def test_b3_weekend_hours_and_pricing_multiplier(mock_db, mock_cache):
    """B3 Test: Weekend dates apply 1.1x pricing multiplier."""
    service = ShowtimeService(mock_db, mock_cache)

    movie = Movie(id=601, title="Weekend Blockbuster", popularity=50.0, duration_minutes=120, status=MovieStatus.NOW_SHOWING, is_active=True)
    movie.movie_genres = []
    std_room = Room(id=1, name="Standard 1", room_type=RoomType.STANDARD, is_active=True, seats=[])

    mock_db.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [movie])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [std_room])),
    ]

    # Pick upcoming Saturday (weekend)
    saturday_d = date.today() + timedelta(days=(5 - date.today().weekday()) % 7)
    if saturday_d <= date.today():
        saturday_d += timedelta(days=7)

    req = AutoScheduleRequest(
        start_date=saturday_d.isoformat(),
        end_date=saturday_d.isoformat(),
        start_time_str="13:00",  # Standard time band (1.0x multiplier)
        end_time_str="17:00",
        base_price=Decimal("100000"),
        vip_price=Decimal("120000"),
        auto_pricing_by_room_type=False,
    )

    proposed = await service.generate_auto_schedule_preview(req)
    assert len(proposed) > 0

    # Base price 100000 * 1.0 (standard band) * 1.1 (weekend) = 110000
    assert proposed[0].base_price == Decimal("110000")


@pytest.mark.asyncio
async def test_b4_eager_loaded_room_capacity_sorting(mock_db, mock_cache):
    """B4 Test: Rooms are sorted descending by seat capacity before movie assignment."""
    service = ShowtimeService(mock_db, mock_cache)

    movie = Movie(id=701, title="IMAX Movie", popularity=80.0, duration_minutes=120, status=MovieStatus.NOW_SHOWING, is_active=True)
    movie.movie_genres = []

    small_room = Room(id=1, name="Small Room", room_type=RoomType.STANDARD, is_active=True, seats=[MagicMock()] * 20)
    large_room = Room(id=2, name="Large Room", room_type=RoomType.STANDARD, is_active=True, seats=[MagicMock()] * 200)

    # Return rooms in order small_room, large_room
    mock_db.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [movie])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [small_room, large_room])),
    ]

    target_d = (date.today() + timedelta(days=1)).isoformat()
    req = AutoScheduleRequest(
        start_date=target_d,
        end_date=target_d,
        start_time_str="10:00",
        end_time_str="13:00",
        base_price=Decimal("100000"),
        vip_price=Decimal("120000"),
    )

    proposed = await service.generate_auto_schedule_preview(req)
    assert len(proposed) > 0
    # Large room (room_id=2) must be scheduled first
    assert proposed[0].room_id == 2
