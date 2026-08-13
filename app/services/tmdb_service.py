from datetime import date
from typing import Any, Dict, List, Optional

import httpx
import structlog

from app.config import settings
from app.core.exceptions import NotFoundException

logger = structlog.get_logger()

# Default HTTP headers to bypass Cloudflare bot/SSL restrictions
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class TMDBService:
    """Service to interact with The Movie Database (TMDB) API with localized region support."""

    def __init__(self):
        self.base_url = settings.TMDB_BASE_URL.rstrip('/')
        self.api_key = (settings.TMDB_API_KEY or "").strip()
        self.image_base_url = settings.TMDB_IMAGE_BASE_URL.rstrip('/')
        self.region = settings.TMDB_REGION
        self.language = settings.TMDB_LANGUAGE

    def _get_auth_headers_and_params(self, extra_params: Optional[Dict[str, Any]] = None) -> tuple[Dict[str, str], Dict[str, Any]]:
        """
        Dynamically handles TMDB Authentication:
        - If api_key is a JWT string starting with 'eyJ' (v4 Read Access Token), pass 'Authorization: Bearer <token>' header.
        - Otherwise pass 'api_key' query parameter (v3 API key).
        """
        headers = dict(DEFAULT_HEADERS)
        params = dict(extra_params or {})

        if self.api_key:
            if self.api_key.startswith("eyJ"):
                headers["Authorization"] = f"Bearer {self.api_key}"
            else:
                params["api_key"] = self.api_key

        return headers, params

    def _get_client(self, headers: Dict[str, str]) -> httpx.AsyncClient:
        """Create httpx AsyncClient configured for HTTP/1.1 and custom headers."""
        return httpx.AsyncClient(
            headers=headers,
            http2=False,
            timeout=15.0,
        )

    def _build_image_url(self, path: Optional[str]) -> Optional[str]:
        """Safely construct poster/backdrop full URL without duplicating prefixes or slashes."""
        if not path:
            return None
        if path.startswith("http://") or path.startswith("https://"):
            return path
        clean_path = path.lstrip('/')
        return f"{self.image_base_url}/{clean_path}"

    async def get_movie(self, tmdb_id: int) -> Dict[str, Any]:
        """Fetch movie data from TMDB API with localized region release date."""
        headers, params = self._get_auth_headers_and_params({
            "language": self.language,
            "append_to_response": "release_dates",
        })

        async with self._get_client(headers) as client:
            response = await client.get(
                f"{self.base_url}/movie/{tmdb_id}",
                params=params,
            )

        if response.status_code == 404:
            raise NotFoundException("TMDB Movie", tmdb_id)

        response.raise_for_status()
        data = response.json()

        # Parse release_date: Try region-specific release date first (e.g. VN)
        release_date = None
        region_results = data.get("release_dates", {}).get("results", [])
        matched_region = next((r for r in region_results if r.get("iso_3166_1") == self.region), None)

        if matched_region and matched_region.get("release_dates"):
            rd_list = matched_region["release_dates"]
            # Prefer theatrical release (type 3 or 2), fallback to first available
            theatrical = next((rd for rd in rd_list if rd.get("type") in (2, 3)), None) or rd_list[0]
            if theatrical.get("release_date"):
                try:
                    release_date = date.fromisoformat(theatrical["release_date"].split("T")[0])
                except (ValueError, TypeError):
                    pass

        # Fallback to primary global release_date if region date was not found
        if not release_date and data.get("release_date"):
            try:
                release_date = date.fromisoformat(data["release_date"])
            except (ValueError, TypeError):
                pass

        # Build poster URL safely
        poster_url = self._build_image_url(data.get("poster_path"))

        # Extract genres
        genre_names = [g["name"] for g in data.get("genres", []) if isinstance(g, dict) and "name" in g]

        return {
            "tmdb_id": data["id"],
            "title": data["title"],
            "overview": data.get("overview"),
            "poster_url": poster_url,
            "runtime": data.get("runtime"),
            "release_date": release_date,
            "original_language": data.get("original_language"),
            "vote_average": data.get("vote_average"),
            "popularity": data.get("popularity"),
            "genres": genre_names,
        }

    async def search_movies(self, query: str, page: int = 1) -> Dict[str, Any]:
        """Search TMDB for movies by query."""
        headers, params = self._get_auth_headers_and_params({
            "query": query,
            "page": page,
            "language": self.language,
            "region": self.region,
        })

        async with self._get_client(headers) as client:
            response = await client.get(
                f"{self.base_url}/search/movie",
                params=params,
            )

        response.raise_for_status()
        data = response.json()

        results = []
        for movie in data.get("results", []):
            poster_url = self._build_image_url(movie.get("poster_path"))
            results.append({
                "tmdb_id": movie["id"],
                "title": movie["title"],
                "overview": movie.get("overview"),
                "poster_url": poster_url,
                "release_date": movie.get("release_date"),
                "popularity": movie.get("popularity"),
            })

        return {
            "results": results,
            "total_results": data.get("total_results", 0),
            "total_pages": data.get("total_pages", 0),
            "page": data.get("page", 1),
        }

    async def get_popular_movies(self, page: int = 1) -> Dict[str, Any]:
        """Get popular movies from TMDB."""
        headers, params = self._get_auth_headers_and_params({
            "page": page,
            "language": self.language,
            "region": self.region,
        })

        async with self._get_client(headers) as client:
            response = await client.get(
                f"{self.base_url}/movie/popular",
                params=params,
            )

        response.raise_for_status()
        data = response.json()

        results = []
        for movie in data.get("results", []):
            poster_url = self._build_image_url(movie.get("poster_path"))
            results.append({
                "tmdb_id": movie["id"],
                "title": movie["title"],
                "overview": movie.get("overview"),
                "poster_url": poster_url,
                "release_date": movie.get("release_date"),
                "popularity": movie.get("popularity"),
            })

        return {
            "results": results,
            "total_results": data.get("total_results", 0),
            "total_pages": data.get("total_pages", 0),
        }

    async def get_now_playing_movies(self, page: int = 1) -> Dict[str, Any]:
        """Get currently playing movies in theaters from TMDB for configured region."""
        headers, params = self._get_auth_headers_and_params({
            "page": page,
            "language": self.language,
            "region": self.region,
        })

        async with self._get_client(headers) as client:
            response = await client.get(
                f"{self.base_url}/movie/now_playing",
                params=params,
            )

        response.raise_for_status()
        data = response.json()

        results = []
        for movie in data.get("results", []):
            poster_url = self._build_image_url(movie.get("poster_path"))
            results.append({
                "tmdb_id": movie["id"],
                "title": movie["title"],
                "overview": movie.get("overview"),
                "poster_url": poster_url,
                "release_date": movie.get("release_date"),
                "popularity": movie.get("popularity"),
            })

        return {
            "results": results,
            "total_results": data.get("total_results", 0),
            "total_pages": data.get("total_pages", 0),
            "page": data.get("page", 1),
        }

    async def get_upcoming_movies(self, page: int = 1) -> Dict[str, Any]:
        """Get upcoming movies from TMDB for configured region."""
        headers, params = self._get_auth_headers_and_params({
            "page": page,
            "language": self.language,
            "region": self.region,
        })

        async with self._get_client(headers) as client:
            response = await client.get(
                f"{self.base_url}/movie/upcoming",
                params=params,
            )

        response.raise_for_status()
        data = response.json()

        results = []
        for movie in data.get("results", []):
            poster_url = self._build_image_url(movie.get("poster_path"))
            results.append({
                "tmdb_id": movie["id"],
                "title": movie["title"],
                "overview": movie.get("overview"),
                "poster_url": poster_url,
                "release_date": movie.get("release_date"),
                "popularity": movie.get("popularity"),
            })

        return {
            "results": results,
            "total_results": data.get("total_results", 0),
            "total_pages": data.get("total_pages", 0),
            "page": data.get("page", 1),
        }
