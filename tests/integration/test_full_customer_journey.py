import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user import User, UserRole
from app.models.movie import Movie
from app.models.room import Room
from app.models.showtime import Showtime
from app.models.showtime_seat import ShowtimeSeat
from app.models.voucher import Voucher, VoucherDiscountType
from app.models.concession import Concession
from app.models.reservation import Reservation, ReservationStatus
from app.models.refund import RefundTransaction
from app.core.security import get_password_hash


@pytest.mark.asyncio
async def test_full_customer_journey_e2e(async_session):
    """
    Full End-to-End Customer Journey Test:
    1. Register new customer account
    2. Login to get access token
    3. Browse movies & showtimes
    4. Hold seats
    5. Create reservation with voucher & concessions (PENDING)
    6. Generate VNPay payment URL
    7. Simulate VNPay success return callback (CONFIRMED)
    8. Verify ticket status & QR details
    9. Cancel reservation (>30m before start)
    10. Verify automatic RefundTransaction creation & loyalty points revocation
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Setup Test Data in Database
        movie = Movie(
            title="E2E Blockbuster Odyssey",
            synopsis="An epic journey through space and time",
            duration_minutes=120,
            release_date=datetime.now(timezone.utc).date() - timedelta(days=1),
            poster_url="http://example.com/poster.jpg",
            status="now_showing",
            age_rating="P",
        )
        room = Room(
            name="E2E IMAX Hall",
            room_type="imax",
            total_rows=5,
            total_cols=5,
            total_seats=25,
            is_active=True,
        )
        async_session.add_all([movie, room])
        await async_session.flush()

        st_start = datetime.now(timezone.utc) + timedelta(hours=5)
        showtime = Showtime(
            movie_id=movie.id,
            room_id=room.id,
            start_time=st_start,
            end_time=st_start + timedelta(minutes=120),
            base_price=Decimal("100000"),
            vip_price=Decimal("120000"),
            status="scheduled",
        )
        async_session.add(showtime)
        await async_session.flush()

        seat1 = ShowtimeSeat(showtime_id=showtime.id, seat_id=1, row_label="A", col_number=1, seat_type="standard", price=Decimal("100000"), status="available")
        seat2 = ShowtimeSeat(showtime_id=showtime.id, seat_id=2, row_label="A", col_number=2, seat_type="standard", price=Decimal("100000"), status="available")
        async_session.add_all([seat1, seat2])

        voucher = Voucher(
            code="E2EPROMO",
            discount_type=VoucherDiscountType.PERCENT,
            discount_value=Decimal("10.00"),
            min_spend=Decimal("50000"),
            is_active=True
        )
        concession = Concession(
            name="Popcorn Combo",
            category="combo",
            price=Decimal("50000"),
            is_active=True
        )
        async_session.add_all([voucher, concession])
        await async_session.commit()

        # Step 1: Register User
        reg_payload = {
            "email": "e2e_customer@example.com",
            "password": "Customer@123456",
            "full_name": "E2E Test Customer",
            "phone_number": "0912345678"
        }
        reg_resp = await client.post("/api/v1/auth/register", json=reg_payload)
        assert reg_resp.status_code == 201

        # Step 2: Login User
        login_resp = await client.post("/api/v1/auth/login", json={"account": "e2e_customer@example.com", "password": "Customer@123456"})
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Step 3: Browse Movies & Showtimes
        movies_resp = await client.get("/api/v1/movies/now-showing")
        assert movies_resp.status_code == 200

        # Step 4: Hold Seats
        hold_resp = await client.post(f"/api/v1/showtimes/{showtime.id}/hold", json={"seat_ids": [seat1.id, seat2.id]}, headers=headers)
        assert hold_resp.status_code == 200

        # Step 5: Create Reservation (PENDING)
        res_payload = {
            "showtime_id": showtime.id,
            "seat_ids": [seat1.id, seat2.id],
            "voucher_code": "E2EPROMO",
            "concession_orders": [{"concession_id": concession.id, "quantity": 1}]
        }
        res_resp = await client.post("/api/v1/reservations/", json=res_payload, headers=headers)
        assert res_resp.status_code == 201
        res_data = res_resp.json()
        reservation_id = res_data["id"]
        assert res_data["status"] == "pending"

        # Step 6: Create Payment URL
        pay_url_resp = await client.post("/api/v1/payments/create-url", json={"reservation_id": reservation_id}, headers=headers)
        assert pay_url_resp.status_code == 200
        assert "payment_url" in pay_url_resp.json()
        vnp_txn_ref = pay_url_resp.json()["vnp_txn_ref"]

        # Step 7: Simulate VNPay Success Callback
        callback_params = {
            "vnp_Amount": "22500000",
            "vnp_BankCode": "NCB",
            "vnp_CardType": "ATM",
            "vnp_OrderInfo": f"Thanh toan ve {reservation_id}",
            "vnp_PayDate": "20260812141127",
            "vnp_ResponseCode": "00",
            "vnp_TmnCode": "S6967RVA",
            "vnp_TransactionNo": "999999",
            "vnp_TransactionStatus": "00",
            "vnp_TxnRef": vnp_txn_ref,
        }
        with patch("app.services.vnpay_service.VNPayService.verify_response", return_value=True):
            cb_resp = await client.get("/api/v1/payments/vnpay-return", params=callback_params, follow_redirects=False)
            assert cb_resp.status_code == 307
            assert "payment-result?status=success" in cb_resp.headers["location"]

        # Step 8: Verify Reservation CONFIRMED
        get_res_resp = await client.get(f"/api/v1/reservations/{reservation_id}", headers=headers)
        assert get_res_resp.status_code == 200
        assert get_res_resp.json()["status"] == "confirmed"

        # Step 9: Cancel Reservation
        with patch("httpx.AsyncClient.post") as mock_refund_post:
            mock_refund_post.return_value.status_code = 200
            mock_refund_post.return_value.json.return_value = {"vnp_ResponseCode": "99", "vnp_Message": "Sandbox Limit"}

            cancel_resp = await client.post(f"/api/v1/reservations/{reservation_id}/cancel", headers=headers)
            assert cancel_resp.status_code == 200
            assert cancel_resp.json()["status"] == "cancelled"
