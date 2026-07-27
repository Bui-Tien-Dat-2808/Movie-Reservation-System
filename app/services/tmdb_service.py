from datetime import date
from typing import Any, Dict, List, Optional

import httpx
import structlog

from app.config import settings
from app.core.exceptions import NotFoundException

logger = structlog.get_logger()


class TMDBService:
    """Service to interact with The Movie Database (TMDB) API."""

    def __init__(self):
        self.base_url = settings.TMDB_BASE_URL
        self.api_key = settings.TMDB_API_KEY
        self.image_base_url = settings.TMDB_IMAGE_BASE_URL

    async def get_movie(self, tmdb_id: int) -> Dict[str, Any]:
        """Fetch movie data from TMDB API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/movie/{tmdb_id}",
                params={"api_key": self.api_key, "language": "en-US"},
                timeout=10.0,
            )

        if response.status_code == 404:
            raise NotFoundException("TMDB Movie", tmdb_id)

        response.raise_for_status()
        data = response.json()

        # Parse release_date
        release_date = None
        if data.get("release_date"):
            try:
                release_date = date.fromisoformat(data["release_date"])
            except ValueError:
                pass

        # Build poster URL
        poster_url = None
        if data.get("poster_path"):
            poster_url = f"{self.image_base_url}{data['poster_path']}"

        # Extract genres
        genre_names = [g["name"] for g in data.get("genres", [])]

        return {
            "tmdb_id": data["id"],
            "title": data["title"],
            "overview": data.get("overview"),
            "poster_url": poster_url,
            "runtime": data.get("runtime"),
            "release_date": release_date,
            "original_language": data.get("original_language"),
            "vote_average": data.get("vote_average"),
            "genres": genre_names,
        }

    async def search_movies(self, query: str, page: int = 1) -> Dict[str, Any]:
        """Search TMDB for movies by query."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/search/movie",
                params={
                    "api_key": self.api_key,
                    "query": query,
                    "page": page,
                    "language": "en-US",
                },
                timeout=10.0,
            )

        response.raise_for_status()
        data = response.json()

        results = []
        for movie in data.get("results", []):
            poster_url = None
            if movie.get("poster_path"):
                poster_url = f"{self.image_base_url}{movie['poster_path']}"

            results.append({
                "tmdb_id": movie["id"],
                "title": movie["title"],
                "overview": movie.get("overview"),
                "poster_url": poster_url,
                "release_date": movie.get("release_date"),
            })

        return {
            "results": results,
            "total_results": data.get("total_results", 0),
            "total_pages": data.get("total_pages", 0),
            "page": data.get("page", 1),
        }

    async def get_popular_movies(self, page: int = 1) -> Dict[str, Any]:
        """Get popular movies from TMDB."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/movie/popular",
                params={"api_key": self.api_key, "page": page, "language": "en-US"},
                timeout=10.0,
            )

        response.raise_for_status()
        data = response.json()

        results = []
        for movie in data.get("results", []):
            poster_url = None
            if movie.get("poster_path"):
                poster_url = f"{self.image_base_url}{movie['poster_path']}"
            results.append({
                "tmdb_id": movie["id"],
                "title": movie["title"],
                "overview": movie.get("overview"),
                "poster_url": poster_url,
                "release_date": movie.get("release_date"),
            })

        return {
            "results": results,
            "total_results": data.get("total_results", 0),
            "total_pages": data.get("total_pages", 0),
        }

    async def get_list_movies(self, list_id: str, page: int = 1) -> Dict[str, Any]:
        """Get movies from a specific TMDB list."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/list/{list_id}",
                params={"api_key": self.api_key, "page": page, "language": "en-US"},
                timeout=10.0,
            )

        if response.status_code == 404:
            raise NotFoundException("TMDB List", list_id)

        response.raise_for_status()
        data = response.json()

        results = []
        for movie in data.get("items", []):
            poster_url = None
            if movie.get("poster_path"):
                poster_url = f"{self.image_base_url}{movie['poster_path']}"
            results.append({
                "tmdb_id": movie["id"],
                "title": movie["title"],
                "overview": movie.get("overview"),
                "poster_url": poster_url,
                "release_date": movie.get("release_date"),
            })

        return {
            "list_name": data.get("name"),
            "description": data.get("description"),
            "results": results,
            "total_results": data.get("total_results", data.get("item_count", 0)),
            "total_pages": data.get("total_pages", 1),
            "page": data.get("page", 1),
        }

