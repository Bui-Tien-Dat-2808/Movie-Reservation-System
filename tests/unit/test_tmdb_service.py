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


class TestTMDBTrailerSelection:
    """Test TMDBService._select_best_trailer logic."""

    def test_official_youtube_trailer_selected(self):
        service = TMDBService()
        videos = [
            {"site": "YouTube", "key": "teaser1", "type": "Teaser", "official": False},
            {"site": "YouTube", "key": "official_trailer", "type": "Trailer", "official": True, "iso_639_1": "en"},
            {"site": "YouTube", "key": "trailer2", "type": "Trailer", "official": False},
        ]
        assert service._select_best_trailer(videos) == "https://www.youtube.com/embed/official_trailer"

    def test_unofficial_trailer_selected_over_teaser(self):
        service = TMDBService()
        videos = [
            {"site": "YouTube", "key": "teaser1", "type": "Teaser", "official": True},
            {"site": "YouTube", "key": "unofficial_trailer", "type": "Trailer", "official": False},
        ]
        assert service._select_best_trailer(videos) == "https://www.youtube.com/embed/unofficial_trailer"

    def test_teaser_selected_when_no_trailer(self):
        service = TMDBService()
        videos = [
            {"site": "YouTube", "key": "clip1", "type": "Clip", "official": False},
            {"site": "YouTube", "key": "teaser_key", "type": "Teaser", "official": True},
        ]
        assert service._select_best_trailer(videos) == "https://www.youtube.com/embed/teaser_key"

    def test_non_youtube_video_ignored(self):
        service = TMDBService()
        videos = [
            {"site": "Vimeo", "key": "vimeo123", "type": "Trailer", "official": True},
        ]
        assert service._select_best_trailer(videos) is None

    def test_missing_key_ignored(self):
        service = TMDBService()
        videos = [
            {"site": "YouTube", "key": "", "type": "Trailer", "official": True},
            {"site": "YouTube", "key": None, "type": "Trailer", "official": True},
        ]
        assert service._select_best_trailer(videos) is None


@pytest.mark.asyncio
async def test_get_movie_detail_skips_tmdb_when_data_exists_in_db():
    """Test get_movie API endpoint skips calling TMDB when director, cast, and trailer exist in DB."""
    from datetime import datetime, timezone
    from app.models.movie import Movie, MovieStatus
    from app.api.v1.movies import get_movie

    mock_service = MagicMock()
    mock_db = MagicMock()

    existing_movie = Movie(
        id=10,
        title="Existing Movie",
        director="Christopher Nolan",
        trailer_url="https://www.youtube.com/embed/existing_key",
        cast_json='[{"name": "Actor A"}]',
        rating="PG-13",
        tmdb_id=500,
        status=MovieStatus.NOW_SHOWING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        is_active=True,
    )

    async def mock_get(movie_id):
        return existing_movie

    mock_service.get_movie = mock_get

    with patch("app.api.v1.movies.TMDBService") as mock_tmdb_cls:
        res = await get_movie(movie_id=10, service=mock_service)
        # Verify TMDBService was NOT instantiated since all fields were present
        mock_tmdb_cls.assert_not_called()
        assert res.director == "Christopher Nolan"
        assert res.trailer_url == "https://www.youtube.com/embed/existing_key"
        cast_name = res.cast[0].name if hasattr(res.cast[0], "name") else res.cast[0]["name"]
        assert cast_name == "Actor A"
