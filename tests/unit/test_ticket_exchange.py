import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock

from app.models.reservation import Reservation, ReservationStatus, ReservationSeat
from app.models.showtime import Showtime, ShowtimeStatus
from app.models.showtime_seat import ShowtimeSeat, SeatStatus
from app.schemas.reservation import ReservationExchangeRequest
from app.services.reservation_service import ReservationService
from app.core.exceptions import ValidationException


@pytest.mark.asyncio
async def test_exchange_reservation_deferred_status_until_payment():
    """Test that exchange_reservation creates a PENDING reservation linked to old reservation, keeping old ticket CONFIRMED until payment."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_cache = MagicMock()
    mock_cache.delete_pattern = AsyncMock()

    service = ReservationService(mock_db, mock_cache)

    now = datetime.now(timezone.utc)
    future_start = now + timedelta(hours=5)

    old_showtime = Showtime(id=1, movie_id=10, room_id=100, start_time=future_start, end_time=future_start + timedelta(hours=2))
    old_res = Reservation(
        id=5,
        user_id=42,
        showtime_id=1,
        status=ReservationStatus.CONFIRMED,
        total_price=Decimal("90000"),
        voucher_code=None,
        showtime=old_showtime,
    )
    old_rs = ReservationSeat(id=50, reservation_id=5, showtime_seat_id=500, price=Decimal("90000"))
    old_res.reservation_seats = [old_rs]
    old_ss = ShowtimeSeat(id=500, showtime_id=1, seat_id=1000, status=SeatStatus.BOOKED)

    # Mock DB returns old reservation
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: old_res),
    ]

    # Mock create_reservation for new showtime (PENDING)
    new_res = Reservation(id=6, user_id=42, showtime_id=2, status=ReservationStatus.PENDING, total_price=Decimal("90000"))
    service.create_reservation = AsyncMock(return_value=new_res)

    req = ReservationExchangeRequest(new_showtime_id=2, new_seat_ids=[501])

    result = await service.exchange_reservation(reservation_id=5, user_id=42, data=req)

    # 1. New reservation is created and linked to old reservation
    assert result.id == 6
    assert result.exchanged_from_reservation_id == 5
    # 2. Old reservation & seats REMAIN CONFIRMED / BOOKED before payment!
    assert old_res.status == ReservationStatus.CONFIRMED
    assert old_ss.status == SeatStatus.BOOKED


@pytest.mark.asyncio
async def test_exchange_reservation_past_time_limit_raises():
    """Test that exchanging less than 30 minutes before showtime raises ValidationException."""
    mock_db = MagicMock()
    mock_cache = MagicMock()
    service = ReservationService(mock_db, mock_cache)

    now = datetime.now(timezone.utc)
    imminent_start = now + timedelta(minutes=15)  # less than 30 mins

    old_showtime = Showtime(id=1, movie_id=10, room_id=100, start_time=imminent_start, end_time=imminent_start + timedelta(hours=2))
    old_res = Reservation(
        id=5,
        user_id=42,
        showtime_id=1,
        status=ReservationStatus.CONFIRMED,
        total_price=Decimal("90000"),
        showtime=old_showtime,
    )

    service.get_reservation = AsyncMock(return_value=old_res)
    req = ReservationExchangeRequest(new_showtime_id=2, new_seat_ids=[501])

    with pytest.raises(ValidationException) as exc_info:
        await service.exchange_reservation(reservation_id=5, user_id=42, data=req)

    assert "30 phút" in str(exc_info.value)
