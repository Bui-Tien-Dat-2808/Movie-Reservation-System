"""Integration tests for Movies API."""
import pytest
from httpx import AsyncClient

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
            "status": "active",
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

    async def test_update_movie(self, client: AsyncClient, test_admin):
        """Admin should be able to update a movie."""
        headers = get_auth_headers(test_admin)

        # Create movie first
        create_resp = await client.post("/api/v1/movies/", json={
            "title": "Original Title",
            "status": "active",
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
            "status": "active",
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
        assert response.json()["name"] == "Action"

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
