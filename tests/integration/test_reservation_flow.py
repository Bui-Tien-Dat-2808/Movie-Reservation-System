"""Integration tests for Reservation flow."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.movie import Movie, MovieStatus
from app.models.seat import Seat, SeatType
from app.models.showtime import Showtime, ShowtimeStatus
from app.models.showtime_seat import ShowtimeSeat, SeatStatus
from app.models.room import Room
from tests.conftest import get_auth_headers


async def create_test_showtime(db: AsyncSession) -> tuple:
    """Helper: create a movie, room, seats, and showtime for testing."""
    # Movie
    movie = Movie(title="Test Movie", status=MovieStatus.NOW_SHOWING, is_active=True)
    db.add(movie)
    await db.flush()

    # Room
    room = Room(name="Test Room", total_rows=2, total_cols=5, is_active=True)
    db.add(room)
    await db.flush()

    # Seats
    seats = []
    for row in ["A", "B"]:
        for col in range(1, 6):
            seat = Seat(
                room_id=room.id,
                row_label=row,
                col_number=col,
                seat_type=SeatType.STANDARD,
                is_active=True,
            )
            db.add(seat)
            await db.flush()
            seats.append(seat)

    # Showtime
    start = datetime.now(timezone.utc) + timedelta(days=3)
    end = start + timedelta(hours=2)
    showtime = Showtime(
        movie_id=movie.id,
        room_id=room.id,
        start_time=start,
        end_time=end,
        base_price=Decimal("15.00"),
        vip_price=Decimal("25.00"),
        status=ShowtimeStatus.SCHEDULED,
    )
    db.add(showtime)
    await db.flush()

    # ShowtimeSeats
    showtime_seats = []
    for seat in seats:
        ss = ShowtimeSeat(
            showtime_id=showtime.id,
            seat_id=seat.id,
            status=SeatStatus.AVAILABLE,
        )
        db.add(ss)
        await db.flush()
        showtime_seats.append(ss)

    await db.commit()
    return movie, room, seats, showtime, showtime_seats


class TestReservationFlow:
    async def test_create_reservation(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        """User should be able to reserve available seats."""
        movie, room, seats, showtime, showtime_seats = await create_test_showtime(db_session)
        headers = get_auth_headers(test_user)

        seat_ids = [seats[0].id, seats[1].id]
        # Hold first
        hold_resp = await client.post(f"/api/v1/showtimes/{showtime.id}/hold", json={
            "seat_ids": seat_ids,
        }, headers=headers)
        assert hold_resp.status_code == 200

        response = await client.post("/api/v1/reservations/", json={
            "showtime_id": showtime.id,
            "seat_ids": seat_ids,
        }, headers=headers)

        assert response.status_code == 201
        data = response.json()
        assert data["showtime_id"] == showtime.id
        assert data["status"] == "pending"
        assert len(data["reservation_seats"]) == 2

    async def test_reservation_unauthenticated(self, client: AsyncClient, db_session: AsyncSession):
        """Unauthenticated users cannot make reservations."""
        _, _, seats, showtime, _ = await create_test_showtime(db_session)
        response = await client.post("/api/v1/reservations/", json={
            "showtime_id": showtime.id,
            "seat_ids": [seats[0].id],
        })
        assert response.status_code == 401

    async def test_get_my_reservations(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        """User should see their own reservations."""
        _, _, seats, showtime, _ = await create_test_showtime(db_session)
        headers = get_auth_headers(test_user)

        # Hold first
        hold_resp = await client.post(f"/api/v1/showtimes/{showtime.id}/hold", json={
            "seat_ids": [seats[0].id],
        }, headers=headers)
        assert hold_resp.status_code == 200

        # Create a reservation first
        await client.post("/api/v1/reservations/", json={
            "showtime_id": showtime.id,
            "seat_ids": [seats[0].id],
        }, headers=headers)

        response = await client.get("/api/v1/reservations/", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] >= 1

    async def test_cancel_reservation(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        """User should be able to cancel upcoming reservation."""
        _, _, seats, showtime, _ = await create_test_showtime(db_session)
        headers = get_auth_headers(test_user)

        # Hold first
        hold_resp = await client.post(f"/api/v1/showtimes/{showtime.id}/hold", json={
            "seat_ids": [seats[0].id],
        }, headers=headers)
        assert hold_resp.status_code == 200

        create_resp = await client.post("/api/v1/reservations/", json={
            "showtime_id": showtime.id,
            "seat_ids": [seats[0].id],
        }, headers=headers)
        reservation_id = create_resp.json()["id"]

        cancel_resp = await client.delete(f"/api/v1/reservations/{reservation_id}", headers=headers)
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

    async def test_admin_revenue_report(
        self, client: AsyncClient, test_admin, db_session: AsyncSession
    ):
        """Admin should access revenue report."""
        headers = get_auth_headers(test_admin)
        response = await client.get("/api/v1/reservations/admin/report/revenue", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_revenue" in data
        assert "total_reservations" in data

    async def test_admin_capacity_report(
        self, client: AsyncClient, test_admin
    ):
        """Admin should access capacity report."""
        headers = get_auth_headers(test_admin)
        response = await client.get("/api/v1/reservations/admin/report/capacity", headers=headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_user_cannot_access_admin_report(
        self, client: AsyncClient, test_user
    ):
        """Regular user should not access admin reports."""
        headers = get_auth_headers(test_user)
        response = await client.get("/api/v1/reservations/admin/report/revenue", headers=headers)
        assert response.status_code == 403


class TestReservationShowtimeSummary:
    """Tests that reservation responses embed ShowtimeSummary (movie_title, room_name, etc.)."""

    async def test_reservation_detail_includes_showtime_summary(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        """Reservation detail should include showtime with movie_title and room_name."""
        movie, room, seats, showtime, _ = await create_test_showtime(db_session)
        headers = get_auth_headers(test_user)

        # Hold then create reservation
        await client.post(f"/api/v1/showtimes/{showtime.id}/hold", json={
            "seat_ids": [seats[0].id],
        }, headers=headers)

        create_resp = await client.post("/api/v1/reservations/", json={
            "showtime_id": showtime.id,
            "seat_ids": [seats[0].id],
        }, headers=headers)
        assert create_resp.status_code == 201
        reservation_id = create_resp.json()["id"]

        # Fetch detail
        detail_resp = await client.get(f"/api/v1/reservations/{reservation_id}", headers=headers)
        assert detail_resp.status_code == 200
        data = detail_resp.json()

        # ShowtimeSummary must be present and populated
        assert data["showtime"] is not None
        assert data["showtime"]["id"] == showtime.id
        assert data["showtime"]["movie_title"] == movie.title
        assert data["showtime"]["room_name"] == room.name
        assert "start_time" in data["showtime"]
        assert "end_time" in data["showtime"]

    async def test_my_reservations_list_includes_showtime_summary(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        """GET /reservations/ list should include showtime summary in each item."""
        _, room, seats, showtime, _ = await create_test_showtime(db_session)
        headers = get_auth_headers(test_user)

        # Hold then create
        await client.post(f"/api/v1/showtimes/{showtime.id}/hold", json={
            "seat_ids": [seats[0].id],
        }, headers=headers)
        await client.post("/api/v1/reservations/", json={
            "showtime_id": showtime.id,
            "seat_ids": [seats[0].id],
        }, headers=headers)

        response = await client.get("/api/v1/reservations/", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert data["meta"]["total"] >= 1
        first = data["items"][0]
        # Each item in the list must carry showtime summary
        assert first["showtime"] is not None
        assert "movie_title" in first["showtime"]
        assert "room_name" in first["showtime"]
        assert "start_time" in first["showtime"]

    async def test_admin_reservation_list_includes_showtime_summary(
        self, client: AsyncClient, test_user, test_admin, db_session: AsyncSession
    ):
        """Admin GET /reservations/admin/all should also include showtime summary."""
        _, _, seats, showtime, _ = await create_test_showtime(db_session)
        user_headers = get_auth_headers(test_user)
        admin_headers = get_auth_headers(test_admin)

        # User holds and creates reservation
        await client.post(f"/api/v1/showtimes/{showtime.id}/hold", json={
            "seat_ids": [seats[0].id],
        }, headers=user_headers)
        await client.post("/api/v1/reservations/", json={
            "showtime_id": showtime.id,
            "seat_ids": [seats[0].id],
        }, headers=user_headers)

        # Admin fetches all reservations
        response = await client.get(
            "/api/v1/reservations/admin/all?page=1&page_size=20",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()

        assert data["meta"]["total"] >= 1
        first = data["items"][0]
        assert first["showtime"] is not None
        assert "movie_title" in first["showtime"]
        assert "room_name" in first["showtime"]

