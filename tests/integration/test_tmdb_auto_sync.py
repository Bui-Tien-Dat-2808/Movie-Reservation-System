import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, HTTPStatusError, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_auto_sync_missing_api_key(client: AsyncClient, test_admin: User):
    """Test auto-sync endpoint when TMDB_API_KEY is empty."""
    from tests.conftest import get_auth_headers
    headers = get_auth_headers(test_admin)

    with patch("app.api.v1.movies.TMDBService") as mock_tmdb_cls:
        instance = MagicMock()
        instance.api_key = ""
        mock_tmdb_cls.return_value = instance

        response = await client.post("/api/v1/movies/tmdb/auto-sync?limit=2", headers=headers)
        assert response.status_code == 409
        assert "TMDB_API_KEY chưa được cấu hình" in response.json()["detail"]


@pytest.mark.asyncio
async def test_auto_sync_401_unauthorized(client: AsyncClient, test_admin: User):
    """Test auto-sync endpoint when TMDB returns 401 Unauthorized."""
    from tests.conftest import get_auth_headers
    headers = get_auth_headers(test_admin)

    with patch("app.api.v1.movies.TMDBService") as mock_tmdb_cls:
        instance = MagicMock()
        instance.api_key = "invalid_key"

        req = Request("GET", "https://api.themoviedb.org/3/movie/now_playing")
        resp = Response(401, json={"status_code": 7, "status_message": "Invalid API key"}, request=req)
        
        async def mock_np(*args, **kwargs):
            raise HTTPStatusError("401 Unauthorized", request=req, response=resp)

        instance.get_now_playing_movies = mock_np
        mock_tmdb_cls.return_value = instance

        response = await client.post("/api/v1/movies/tmdb/auto-sync?limit=2", headers=headers)
        assert response.status_code == 409
        assert "401 Unauthorized" in response.json()["detail"]
