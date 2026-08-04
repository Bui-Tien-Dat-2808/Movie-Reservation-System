"""Integration tests for Movies API."""
import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.movie import Movie, MovieStatus
from app.models.room import Room
from app.models.seat import Seat, SeatType
from app.models.showtime import Showtime, ShowtimeStatus
from app.models.showtime_seat import ShowtimeSeat, SeatStatus
from tests.conftest import get_auth_headers


class TestMoviesCRUD:
    async def test_list_movies_empty(self, client: AsyncClient):
        """Should return empty list when no movies."""
        response = await client.get("/api/v1/movies/")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["meta"]["total"] == 0

    async def test_create_movie_as_admin(self, client: AsyncClient, test_admin):
        """Admin should be able to create a movie."""
        headers = get_auth_headers(test_admin)
        response = await client.post("/api/v1/movies/", json={
            "title": "Inception",
            "description": "A mind-bending thriller",
            "duration_minutes": 148,
            "status": "now_showing",
        }, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Inception"
        assert data["duration_minutes"] == 148

    async def test_create_movie_as_user_forbidden(self, client: AsyncClient, test_user):
        """Regular user should not be able to create movies."""
        headers = get_auth_headers(test_user)
        response = await client.post("/api/v1/movies/", json={
            "title": "Unauthorized Movie",
        }, headers=headers)
        assert response.status_code == 403

    async def test_get_movie_not_found(self, client: AsyncClient):
        """Should return 404 for non-existent movie."""
        response = await client.get("/api/v1/movies/99999999")
        assert response.status_code == 404

    async def test_page_size_exceeding_limit_returns_422(self, client: AsyncClient):
        """Request with page_size > 100 should be rejected with HTTP 422."""
        response = await client.get("/api/v1/movies/?page_size=200")
        assert response.status_code == 422

    async def test_update_movie(self, client: AsyncClient, test_admin):
        """Admin should be able to update a movie."""
        headers = get_auth_headers(test_admin)

        # Create movie first
        create_resp = await client.post("/api/v1/movies/", json={
            "title": "Original Title",
            "status": "now_showing",
        }, headers=headers)
        movie_id = create_resp.json()["id"]

        # Update
        update_resp = await client.put(f"/api/v1/movies/{movie_id}", json={
            "title": "Updated Title",
            "description": "New description",
        }, headers=headers)
        assert update_resp.status_code == 200
        assert update_resp.json()["title"] == "Updated Title"

    async def test_delete_movie(self, client: AsyncClient, test_admin):
        """Admin should be able to soft-delete a movie."""
        headers = get_auth_headers(test_admin)

        create_resp = await client.post("/api/v1/movies/", json={
            "title": "To Be Deleted",
            "status": "now_showing",
        }, headers=headers)
        movie_id = create_resp.json()["id"]

        delete_resp = await client.delete(f"/api/v1/movies/{movie_id}", headers=headers)
        assert delete_resp.status_code == 204

        # Should 404 after deletion
        get_resp = await client.get(f"/api/v1/movies/{movie_id}")
        assert get_resp.status_code == 404


class TestGenresCRUD:
    async def test_list_genres_empty(self, client: AsyncClient):
        response = await client.get("/api/v1/genres/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_create_genre(self, client: AsyncClient, test_admin):
        headers = get_auth_headers(test_admin)
        response = await client.post("/api/v1/genres/", json={
            "name": "Action",
            "description": "Action movies",
        }, headers=headers)
        assert response.status_code == 201
        assert response.json()["name"] == "Hành Động"

    async def test_create_duplicate_genre(self, client: AsyncClient, test_admin):
        headers = get_auth_headers(test_admin)
        await client.post("/api/v1/genres/", json={"name": "Drama"}, headers=headers)
        response = await client.post("/api/v1/genres/", json={"name": "Drama"}, headers=headers)
        assert response.status_code == 409


class TestRoomCRUD:
    async def test_create_room(self, client: AsyncClient, test_admin):
        """Admin can create a room with auto-generated seats."""
        headers = get_auth_headers(test_admin)
        response = await client.post("/api/v1/rooms/", json={
            "name": "Screen 1",
            "room_type": "imax",
            "total_rows": 5,
            "total_cols": 10,
        }, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Screen 1"
        # Should have 5 * 10 = 50 seats
        assert data["total_seats"] == 50

    async def test_list_rooms(self, client: AsyncClient):
        response = await client.get("/api/v1/rooms/")
        assert response.status_code == 200


class TestNowShowing:
    """Tests for GET /api/v1/movies/now-showing endpoint."""

    async def test_now_showing_no_auth_required(self, client: AsyncClient):
        """Public endpoint — no authentication required."""
        response = await client.get("/api/v1/movies/now-showing")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "meta" in data

    async def test_now_showing_empty_when_no_movies(self, client: AsyncClient):
        """Should return empty list when DB has no movies."""
        response = await client.get("/api/v1/movies/now-showing")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["meta"]["total"] == 0

    async def test_now_showing_returns_only_now_showing_movies(
        self, client: AsyncClient, test_admin
    ):
        """Should return only movies with status=now_showing, not coming_soon or ended."""
        headers = get_auth_headers(test_admin)

        # Create movies with all 3 statuses
        await client.post("/api/v1/movies/", json={
            "title": "Now Showing Film",
            "status": "now_showing",
        }, headers=headers)
        await client.post("/api/v1/movies/", json={
            "title": "Coming Soon Film",
            "status": "coming_soon",
        }, headers=headers)
        await client.post("/api/v1/movies/", json={
            "title": "Ended Film",
            "status": "ended",
        }, headers=headers)

        response = await client.get("/api/v1/movies/now-showing")
        assert response.status_code == 200
        data = response.json()

        titles = [item["title"] for item in data["items"]]
        assert "Now Showing Film" in titles
        assert "Coming Soon Film" not in titles
        assert "Ended Film" not in titles

    async def test_now_showing_search_filter(self, client: AsyncClient, test_admin):
        """Search filter should work on now-showing endpoint."""
        headers = get_auth_headers(test_admin)

        await client.post("/api/v1/movies/", json={
            "title": "Avengers Endgame",
            "status": "now_showing",
        }, headers=headers)
        await client.post("/api/v1/movies/", json={
            "title": "Interstellar",
            "status": "now_showing",
        }, headers=headers)

        response = await client.get("/api/v1/movies/now-showing?search=Avengers")
        assert response.status_code == 200
        data = response.json()
        titles = [item["title"] for item in data["items"]]
        assert any("Avengers" in t for t in titles)
        assert not any("Interstellar" in t for t in titles)

    async def test_now_showing_pagination(self, client: AsyncClient, test_admin):
        """Pagination should work correctly."""
        headers = get_auth_headers(test_admin)

        # Create 3 now_showing movies
        for i in range(3):
            await client.post("/api/v1/movies/", json={
                "title": f"Movie Paginate {i}",
                "status": "now_showing",
            }, headers=headers)

        response = await client.get("/api/v1/movies/now-showing?page=1&page_size=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 2
        assert data["meta"]["page"] == 1
        assert data["meta"]["page_size"] == 2


class TestShowtimeCRUD:
    """Tests for showtime creation — validates MovieStatus.NOW_SHOWING constraint."""

    async def _create_room(self, client: AsyncClient, headers: dict, name: str = "Test Room") -> int:
        """Helper: create a room and return its ID."""
        resp = await client.post("/api/v1/rooms/", json={
            "name": name,
            "room_type": "standard",
            "total_rows": 3,
            "total_cols": 5,
        }, headers=headers)
        assert resp.status_code == 201
        return resp.json()["id"]

    async def _create_movie(self, client: AsyncClient, headers: dict, status: str, title: str) -> int:
        """Helper: create a movie with given status and return its ID."""
        resp = await client.post("/api/v1/movies/", json={
            "title": title,
            "status": status,
        }, headers=headers)
        assert resp.status_code == 201
        return resp.json()["id"]

    def _showtime_payload(self, movie_id: int, room_id: int) -> dict:
        start = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=2, hours=2)).isoformat()
        return {
            "movie_id": movie_id,
            "room_id": room_id,
            "start_time": start,
            "end_time": end,
            "base_price": "90000.0",
            "vip_price": "120000.0",
        }

    async def test_create_showtime_for_now_showing_movie_succeeds(
        self, client: AsyncClient, test_admin
    ):
        """Showtime creation succeeds for a movie with status=now_showing."""
        headers = get_auth_headers(test_admin)
        movie_id = await self._create_movie(client, headers, "now_showing", "Now Playing Movie")
        room_id = await self._create_room(client, headers, "Room A1")

        resp = await client.post(
            "/api/v1/showtimes/",
            json=self._showtime_payload(movie_id, room_id),
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["movie_id"] == movie_id
        assert data["room_id"] == room_id
        assert data["status"] == "scheduled"

    async def test_create_showtime_for_coming_soon_movie_succeeds(
        self, client: AsyncClient, test_admin
    ):
        """Showtime creation succeeds for a coming_soon movie (pre-sales)."""
        headers = get_auth_headers(test_admin)
        movie_id = await self._create_movie(client, headers, "coming_soon", "Upcoming Movie")
        room_id = await self._create_room(client, headers, "Room B1")

        resp = await client.post(
            "/api/v1/showtimes/",
            json=self._showtime_payload(movie_id, room_id),
            headers=headers,
        )
        assert resp.status_code == 201

    async def test_create_showtime_for_ended_movie_fails(
        self, client: AsyncClient, test_admin
    ):
        """Showtime creation should be rejected for an ended movie (422)."""
        headers = get_auth_headers(test_admin)
        movie_id = await self._create_movie(client, headers, "ended", "Old Movie")
        room_id = await self._create_room(client, headers, "Room C1")

        resp = await client.post(
            "/api/v1/showtimes/",
            json=self._showtime_payload(movie_id, room_id),
            headers=headers,
        )
        assert resp.status_code == 422
        data = resp.json()
        assert "now_showing" in data["detail"].lower() or "coming_soon" in data["detail"].lower()

    async def test_update_showtime_conflict_fails(
        self, client: AsyncClient, test_admin
    ):
        """Updating showtime A to overlap showtime B in same room raises 409 Conflict."""
        headers = get_auth_headers(test_admin)
        movie_id = await self._create_movie(client, headers, "now_showing", "Conflict Movie")
        room_id = await self._create_room(client, headers, "Room D1")

        # Showtime 1: Day 3, 10:00 -> 12:00
        start1 = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=10, minute=0, second=0).isoformat()
        end1 = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=12, minute=0, second=0).isoformat()

        res1 = await client.post("/api/v1/showtimes/", json={
            "movie_id": movie_id, "room_id": room_id,
            "start_time": start1, "end_time": end1,
            "base_price": "90000.0", "vip_price": "120000.0"
        }, headers=headers)
        assert res1.status_code == 201

        # Showtime 2: Day 3, 14:00 -> 16:00
        start2 = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=14, minute=0, second=0).isoformat()
        end2 = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=16, minute=0, second=0).isoformat()

        res2 = await client.post("/api/v1/showtimes/", json={
            "movie_id": movie_id, "room_id": room_id,
            "start_time": start2, "end_time": end2,
            "base_price": "90000.0", "vip_price": "120000.0"
        }, headers=headers)
        assert res2.status_code == 201
        st2_id = res2.json()["id"]

        # Try to update Showtime 2 to overlap Showtime 1 (11:00 -> 13:00)
        overlap_start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=11, minute=0, second=0).isoformat()
        overlap_end = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=13, minute=0, second=0).isoformat()

        upd_res = await client.put(f"/api/v1/showtimes/{st2_id}", json={
            "start_time": overlap_start,
            "end_time": overlap_end
        }, headers=headers)
        assert upd_res.status_code == 409
        assert "conflict" in upd_res.json()["detail"].lower() or "scheduled" in upd_res.json()["detail"].lower()

    async def test_showtime_dynamic_status_transition(
        self, client: AsyncClient, test_admin, db_session: AsyncSession
    ):
        """Showtime status should dynamically transition to ongoing or completed based on time."""
        from app.services.showtime_service import ShowtimeService
        from app.services.cache_service import CacheService
        from tests.integration.test_reservation_flow import create_test_showtime

        _, _, _, showtime, _ = await create_test_showtime(db_session)
        service = ShowtimeService(db_session, CacheService(None))

        # Initially 3 days in future -> SCHEDULED
        st = await service.get_showtime(showtime.id)
        assert st.status == ShowtimeStatus.SCHEDULED

        # Set start_time to past and end_time to future -> ONGOING
        showtime.start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        showtime.end_time = datetime.now(timezone.utc) + timedelta(hours=1)
        await db_session.commit()

        st_ongoing = await service.get_showtime(showtime.id)
        assert st_ongoing.status == ShowtimeStatus.ONGOING

        # Set end_time to past -> COMPLETED
        showtime.end_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        await db_session.commit()

        st_completed = await service.get_showtime(showtime.id)
        assert st_completed.status == ShowtimeStatus.COMPLETED
