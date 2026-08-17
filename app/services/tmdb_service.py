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

    def _select_best_trailer(self, videos: List[Dict[str, Any]]) -> Optional[str]:
        """
        Select best YouTube trailer embed URL based on strict priority:
        1. official == True AND type == "Trailer"
        2. type == "Trailer"
        3. type == "Teaser"
        4. type == "Clip"
        Within the top priority group, prefer matching language (vi/en) and newest published_at.
        Only consider site == "YouTube" with non-empty key.
        Return None if no valid YouTube video found (NO YouTube search URL fallback).
        """
        if not videos or not isinstance(videos, list):
            return None

        # Filter valid YouTube videos
        yt_videos = [
            v for v in videos
            if isinstance(v, dict)
            and v.get("site") == "YouTube"
            and v.get("key")
            and isinstance(v.get("key"), str)
            and v["key"].strip()
        ]

        if not yt_videos:
            return None

        def video_score(v: Dict[str, Any]) -> tuple:
            v_type = (v.get("type") or "").strip()
            is_official = bool(v.get("official"))
            lang = (v.get("iso_639_1") or "").lower()
            pub = str(v.get("published_at") or "")

            if is_official and v_type == "Trailer":
                type_rank = 4
            elif v_type == "Trailer":
                type_rank = 3
            elif v_type == "Teaser":
                type_rank = 2
            elif v_type == "Clip":
                type_rank = 1
            else:
                type_rank = 0

            if lang == "vi":
                lang_rank = 2
            elif lang == "en":
                lang_rank = 1
            else:
                lang_rank = 0

            return (type_rank, lang_rank, pub)

        best = max(yt_videos, key=video_score)

        if video_score(best)[0] == 0:
            return None

        clean_key = best["key"].strip()
        return f"https://www.youtube.com/embed/{clean_key}"

    async def get_movie(self, tmdb_id: int) -> Dict[str, Any]:
        """Fetch movie data from TMDB API with localized region release date, videos, and credits in a single request."""
        headers, params = self._get_auth_headers_and_params({
            "language": self.language,
            "append_to_response": "release_dates,videos,credits",
        })

        try:
            async with self._get_client(headers) as client:
                response = await client.get(
                    f"{self.base_url}/movie/{tmdb_id}",
                    params=params,
                )

            if response.status_code == 404:
                raise NotFoundException("TMDB Movie", tmdb_id)
            if response.status_code == 429:
                logger.warning("TMDB API Rate Limit hit (429)", tmdb_id=tmdb_id, endpoint=f"/movie/{tmdb_id}", status_code=429)
                response.raise_for_status()

            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.warning("TMDB API HTTP error", tmdb_id=tmdb_id, status_code=e.response.status_code, error=str(e))
            raise
        except Exception as e:
            logger.warning("TMDB API request failed", tmdb_id=tmdb_id, error=str(e))
            raise

        # 1. Parse release_date: Try region-specific release date first (e.g. VN)
        release_date = None
        region_results = data.get("release_dates", {}).get("results", [])
        matched_region = next((r for r in region_results if r.get("iso_3166_1") == self.region), None)

        if matched_region and matched_region.get("release_dates"):
            rd_list = matched_region["release_dates"]
            theatrical = next((rd for rd in rd_list if rd.get("type") in (2, 3)), None) or rd_list[0]
            if theatrical.get("release_date"):
                try:
                    release_date = date.fromisoformat(theatrical["release_date"].split("T")[0])
                except (ValueError, TypeError):
                    pass

        if not release_date and data.get("release_date"):
            try:
                release_date = date.fromisoformat(data["release_date"])
            except (ValueError, TypeError):
                pass

        # 2. Build poster URL
        poster_url = self._build_image_url(data.get("poster_path"))

        # 3. Extract genres
        genre_names = [g["name"] for g in data.get("genres", []) if isinstance(g, dict) and "name" in g]

        # 4. Extract trailer URL from videos
        videos_list = data.get("videos", {}).get("results", [])
        trailer_url = self._select_best_trailer(videos_list)

        # 5. Extract credits (director & top cast)
        credits_data = data.get("credits", {})
        crew_list = credits_data.get("crew", [])
        directors = [c.get("name") for c in crew_list if isinstance(c, dict) and c.get("job") == "Director"]
        director_name = directors[0] if directors else None

        cast_list = []
        for c in credits_data.get("cast", [])[:8]:
            if isinstance(c, dict) and c.get("name"):
                cast_list.append({
                    "name": c.get("name"),
                    "character": c.get("character"),
                    "profile_url": self._build_image_url(c.get("profile_path")),
                })

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
            "trailer_url": trailer_url,
            "director": director_name,
            "cast": cast_list,
        }

    async def get_movie_trailer_url(self, tmdb_id: int) -> Optional[str]:
        """Fetch official YouTube trailer embed URL for a movie using standalone videos endpoint if needed."""
        if not tmdb_id or not self.api_key:
            return None
        try:
            headers, params = self._get_auth_headers_and_params({"language": self.language})
            async with self._get_client(headers) as client:
                resp = await client.get(f"{self.base_url}/movie/{tmdb_id}/videos", params=params)

            if resp.status_code == 200:
                results = resp.json().get("results", [])
                return self._select_best_trailer(results)
            elif resp.status_code == 429:
                logger.warning("TMDB rate limit hit (429)", tmdb_id=tmdb_id, endpoint="/videos", status_code=429)
        except Exception as e:
            logger.warning("Failed to fetch TMDB trailer", tmdb_id=tmdb_id, error=str(e))
        return None

    async def get_movie_credits(self, tmdb_id: int) -> Dict[str, Any]:
        """Fetch director and top cast members from TMDB credits endpoint."""
        if not tmdb_id or not self.api_key:
            return {"director": None, "cast": []}
        try:
            headers, params = self._get_auth_headers_and_params({"language": "en-US"})
            async with self._get_client(headers) as client:
                resp = await client.get(f"{self.base_url}/movie/{tmdb_id}/credits", params=params)

            if resp.status_code == 200:
                data = resp.json()
                cast_list = []
                for c in data.get("cast", [])[:8]:
                    if isinstance(c, dict) and c.get("name"):
                        cast_list.append({
                            "name": c.get("name"),
                            "character": c.get("character"),
                            "profile_url": self._build_image_url(c.get("profile_path")),
                        })
                crew_list = data.get("crew", [])
                directors = [c.get("name") for c in crew_list if isinstance(c, dict) and c.get("job") == "Director"]
                director_name = directors[0] if directors else None
                return {"director": director_name, "cast": cast_list}
            elif resp.status_code == 429:
                logger.warning("TMDB rate limit hit (429)", tmdb_id=tmdb_id, endpoint="/credits", status_code=429)
        except Exception as e:
            logger.warning("Failed to fetch TMDB credits", tmdb_id=tmdb_id, error=str(e))
        return {"director": None, "cast": []}

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
