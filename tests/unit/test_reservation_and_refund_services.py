import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, patch

from app.models.reservation import Reservation, ReservationStatus, ReservationSeat
from app.models.showtime import Showtime, ShowtimeStatus
from app.models.showtime_seat import ShowtimeSeat, SeatStatus
from app.models.user import User, UserRole
from app.models.payment import PaymentTransaction
from app.models.refund import RefundTransaction
from app.services.reservation_service import ReservationService
from app.services.refund_service import RefundService
from app.services.loyalty_service import LoyaltyService
from app.core.exceptions import ValidationException, NotFoundException


@pytest.mark.asyncio
async def test_confirm_payment_success_flow():
    """Test confirm_payment_success transitions PENDING to CONFIRMED and awards points."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_cache = AsyncMock()

    service = ReservationService(mock_db, mock_cache)

    showtime = Showtime(id=1, movie_id=10, room_id=100, start_time=datetime.now(timezone.utc) + timedelta(hours=2))
    user = User(id=10, email="user@test.com", loyalty_points=0)
    res = Reservation(
        id=100,
        user_id=10,
        showtime_id=1,
        status=ReservationStatus.PENDING,
        total_price=Decimal("150000"),
        showtime=showtime,
        user=user,
    )
    rs = ReservationSeat(id=1, reservation_id=100, showtime_seat_id=50, price=Decimal("150000"))
    res.reservation_seats = [rs]

    ss = ShowtimeSeat(id=50, showtime_id=1, seat_id=500, status=SeatStatus.HELD)

    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: res), # get_reservation
        MagicMock(scalars=lambda: MagicMock(all=lambda: [rs])), # get reservation seats
        MagicMock(scalars=lambda: MagicMock(all=lambda: [ss])), # get showtime seats
        MagicMock(scalar_one_or_none=lambda: None), # existing PaymentTransaction
        MagicMock(scalar_one_or_none=lambda: user), # user for points
    ]

    with patch("app.services.loyalty_service.LoyaltyService.award_points", new_callable=AsyncMock) as mock_award, \
         patch("app.services.email_service.EmailService.build_ticket_email_html", return_value="<html></html>"), \
         patch("app.services.email_service.EmailService.generate_barcode_bytes", return_value=b"png"):
        
        updated_res = await service.confirm_payment_success(
            reservation_id=100,
            payment_method="vnpay",
            vnp_params={"vnp_TxnRef": "TX100", "vnp_ResponseCode": "00"}
        )

        assert updated_res.status == ReservationStatus.CONFIRMED
        assert ss.status == SeatStatus.BOOKED
        mock_award.assert_called_once()


@pytest.mark.asyncio
async def test_refund_service_list_refunds():
    """Test RefundService list_refunds combining transactions and cash cancellations."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = RefundService(mock_db)

    user = User(id=1, email="test@user.com", full_name="Test User")
    showtime = Showtime(id=1, movie_id=1, room_id=1)
    showtime.movie = MagicMock(title="Action Movie")

    res = Reservation(id=10, ticket_code="CVN-10", notes="[Reason: Tôi không còn nhu cầu xem phim nữa]", user=user, showtime=showtime)
    refund_tx = RefundTransaction(
        id=1,
        reservation_id=10,
        payment_transaction_id=100,
        amount=Decimal("200000"),
        vnp_request_id="RF12345678901234",
        status="success",
        vnpay_response_code="00",
        vnpay_response_message="OK",
        admin_note=None,
        created_at=datetime.now(timezone.utc),
        reservation=res,
    )

    mock_db.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [refund_tx])), # refund_transactions
        MagicMock(scalars=lambda: MagicMock(all=lambda: [])), # standalone cancelled reservations
    ]

    items, total_count = await service.list_refunds(status_filter=None, payment_method_filter=None)

    assert total_count == 1
    assert len(items) == 1
    assert items[0]["id"] == 1
    assert items[0]["vnp_request_id"] == "RF12345678901234"


@pytest.mark.asyncio
async def test_loyalty_service_award_and_revoke():
    """Test LoyaltyService points calculation, awarding and revoking."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    user = User(id=1, email="test@loyalty.com", loyalty_points=100)
    res = Reservation(id=1, user_id=1, total_price=Decimal("200000"), user=user, status=ReservationStatus.CONFIRMED)

    # 1st call for award_points: existing_tx check -> None, user check -> user
    # 2nd call for revoke_points: point_tx check -> PointTransaction
    point_tx = MagicMock(points=200)
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: None),      # award: check existing
        MagicMock(scalar_one_or_none=lambda: user),      # award: fetch user
        MagicMock(scalar_one_or_none=lambda: point_tx),  # revoke: fetch awarded tx
        MagicMock(scalar_one_or_none=lambda: None),      # revoke: check already revoked tx
        MagicMock(scalar_one_or_none=lambda: user),      # revoke: fetch user
    ]

    # Award points
    await LoyaltyService.award_points(mock_db, res)
    assert user.loyalty_points == 300  # 100 + 200 points (200,000 / 1000 = 200)

    # Revoke points
    await LoyaltyService.revoke_points(mock_db, res)
    assert user.loyalty_points == 100
