import pytest
from unittest.mock import patch, MagicMock
import httpx
from datetime import date

from app.services.tmdb_service import TMDBService
from app.core.exceptions import NotFoundException


class DummyAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def get(self, *args, **kwargs):
        return self._response


@pytest.mark.asyncio
async def test_tmdb_service_v3_vs_v4_auth():
    """Test that TMDBService uses query params for v3 key and Bearer header for v4 JWT."""
    # Test v3 API key
    with patch("app.services.tmdb_service.settings") as mock_settings:
        mock_settings.TMDB_BASE_URL = "https://api.themoviedb.org/3"
        mock_settings.TMDB_API_KEY = "1234567890abcdef1234567890abcdef"
        mock_settings.TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
        mock_settings.TMDB_REGION = "VN"
        mock_settings.TMDB_LANGUAGE = "vi-VN"

        service = TMDBService()
        headers, params = service._get_auth_headers_and_params({"page": 1})
        assert "Authorization" not in headers
        assert params.get("api_key") == "1234567890abcdef1234567890abcdef"

    # Test v4 Bearer Token
    with patch("app.services.tmdb_service.settings") as mock_settings:
        mock_settings.TMDB_BASE_URL = "https://api.themoviedb.org/3"
        mock_settings.TMDB_API_KEY = "eyJhbGciOiJIUzI1NiJ9.testtoken"
        mock_settings.TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
        mock_settings.TMDB_REGION = "VN"
        mock_settings.TMDB_LANGUAGE = "vi-VN"

        service = TMDBService()
        headers, params = service._get_auth_headers_and_params({"page": 1})
        assert headers.get("Authorization") == "Bearer eyJhbGciOiJIUzI1NiJ9.testtoken"
        assert "api_key" not in params


@pytest.mark.asyncio
async def test_build_image_url():
    """Test that _build_image_url formats poster paths properly."""
    service = TMDBService()
    assert service._build_image_url(None) is None
    assert service._build_image_url("") is None
    assert service._build_image_url("https://external.com/poster.jpg") == "https://external.com/poster.jpg"
    assert service._build_image_url("/abc.jpg") == "https://image.tmdb.org/t/p/w500/abc.jpg"


@pytest.mark.asyncio
async def test_get_movie_success():
    """Test get_movie with mocked 200 response."""
    service = TMDBService()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock(return_value=None)
    mock_response.json.return_value = {
        "id": 999,
        "title": "Test Movie",
        "overview": "Overview text",
        "poster_path": "/test_poster.jpg",
        "runtime": 120,
        "release_date": "2026-05-15",
        "original_language": "en",
        "vote_average": 8.5,
        "genres": [{"id": 28, "name": "Action"}, {"id": 12, "name": "Adventure"}],
    }

    dummy_client = DummyAsyncClient(mock_response)

    with patch.object(service, "_get_client", return_value=dummy_client):
        movie_data = await service.get_movie(999)

    assert movie_data["tmdb_id"] == 999
    assert movie_data["title"] == "Test Movie"
    assert movie_data["release_date"] == date(2026, 5, 15)
    assert movie_data["genres"] == ["Action", "Adventure"]
    assert "test_poster.jpg" in movie_data["poster_url"]


@pytest.mark.asyncio
async def test_get_movie_not_found():
    """Test get_movie raises NotFoundException when TMDB returns 404."""
    service = TMDBService()
    mock_response = MagicMock()
    mock_response.status_code = 404

    dummy_client = DummyAsyncClient(mock_response)

    with patch.object(service, "_get_client", return_value=dummy_client):
        with pytest.raises(NotFoundException):
            await service.get_movie(999999)


@pytest.mark.asyncio
async def test_get_now_playing_movies():
    """Test get_now_playing_movies with mocked page response."""
    service = TMDBService()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock(return_value=None)
    mock_response.json.return_value = {
        "results": [
            {"id": 101, "title": "Now Playing 1", "poster_path": "/p1.jpg", "release_date": "2026-01-01"},
            {"id": 102, "title": "Now Playing 2", "poster_path": "/p2.jpg", "release_date": "2026-01-02"},
        ],
        "total_results": 2,
        "total_pages": 1,
        "page": 1,
    }

    dummy_client = DummyAsyncClient(mock_response)

    with patch.object(service, "_get_client", return_value=dummy_client):
        data = await service.get_now_playing_movies(page=1)

    assert len(data["results"]) == 2
    assert data["results"][0]["tmdb_id"] == 101


@pytest.mark.asyncio
async def test_get_upcoming_movies():
    """Test get_upcoming_movies with mocked response."""
    service = TMDBService()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock(return_value=None)
    mock_response.json.return_value = {
        "results": [
            {"id": 201, "title": "Upcoming 1", "poster_path": "/u1.jpg", "release_date": "2026-12-01"},
        ],
        "total_results": 1,
        "total_pages": 1,
        "page": 1,
    }

    dummy_client = DummyAsyncClient(mock_response)

    with patch.object(service, "_get_client", return_value=dummy_client):
        data = await service.get_upcoming_movies(page=1)

    assert len(data["results"]) == 1
    assert data["results"][0]["tmdb_id"] == 201
