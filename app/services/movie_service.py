from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import ConflictException, NotFoundException
from app.models.genre import Genre
from app.models.movie import Movie, MovieGenre, MovieStatus
from app.schemas.movie import MovieCreate, MovieUpdate
from app.services.cache_service import CacheService
from app.services.tmdb_service import TMDBService
from app.utils.pagination import PaginationParams

logger = structlog.get_logger()

from app.utils.genre_utils import normalize_genre_name

CACHE_KEY_MOVIES = "movies:list"
CACHE_KEY_MOVIE = "movies:detail:{id}"


class MovieService:
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache

    @staticmethod
    def _infer_status_from_release_date(release_date):
        from datetime import date

        if release_date and release_date > date.today():
            return MovieStatus.COMING_SOON
        return MovieStatus.NOW_SHOWING

    async def auto_update_movie_statuses(self) -> int:
        """
        Efficiently update movie statuses using set operations (4 SQL queries total).
        Returns the number of movie status changes.
        """
        from datetime import date, datetime, timedelta, timezone
        from app.models.showtime import Showtime

        today = date.today()
        now_utc = datetime.now(timezone.utc)
        cutoff_date = today - timedelta(days=35)
        changes = 0

        # 1. Fetch movie_ids with FUTURE showtimes
        fut_res = await self.db.execute(
            select(Showtime.movie_id).where(Showtime.start_time >= now_utc).distinct()
        )
        future_showtime_movie_ids = set(fut_res.scalars().all())

        # 2. Query all active movies and update status deterministically
        res = await self.db.execute(
            select(Movie).where(Movie.is_active == True)
        )
        movies = list(res.scalars().all())

        for m in movies:
            has_future_st = m.id in future_showtime_movie_ids
            old_status = m.status

            if m.release_date and m.release_date > today:
                m.status = MovieStatus.COMING_SOON
            elif m.release_date and m.release_date < cutoff_date and not has_future_st:
                m.status = MovieStatus.ENDED
            else:
                m.status = MovieStatus.NOW_SHOWING

            if m.status != old_status:
                changes += 1

        await self.db.flush()
        if changes > 0 and self.cache:
            try:
                res = self.cache.delete_pattern(f"{CACHE_KEY_MOVIES}*")
                if hasattr(res, "__await__"):
                    await res
            except Exception:
                pass
        return changes

    async def get_movies(
        self,
        pagination: PaginationParams,
        genre_id: Optional[int] = None,
        search: Optional[str] = None,
        status: Optional[MovieStatus] = None,
    ) -> tuple[List[Movie], int]:
        """List movies with filtering and pagination (Redis cached)."""
        from datetime import date, datetime, timezone

        status_str = status.value if status else "all"
        cache_key = f"{CACHE_KEY_MOVIES}:{status_str}:{genre_id or 0}:{search or ''}:{pagination.page}:{pagination.page_size}"

        # 1. Try Redis cache first
        cached = await self.cache.get(cache_key)
        if cached and isinstance(cached, dict):
            items_data = cached.get("items", [])
            total = cached.get("total", 0)
            movies = []
            now_now = datetime.now(timezone.utc)
            for item in items_data:
                m = Movie(
                    id=item["id"],
                    title=item["title"],
                    description=item.get("description"),
                    poster_url=item.get("poster_url"),
                    duration_minutes=item.get("duration_minutes"),
                    release_date=date.fromisoformat(item["release_date"]) if item.get("release_date") else None,
                    language=item.get("language"),
                    tmdb_id=item.get("tmdb_id"),
                    status=MovieStatus(item["status"]) if item.get("status") else MovieStatus.NOW_SHOWING,
                    rating=item.get("rating"),
                    director=item.get("director"),
                    is_active=item.get("is_active", True),
                    created_at=datetime.fromisoformat(item["created_at"]) if item.get("created_at") else now_now,
                    updated_at=datetime.fromisoformat(item["updated_at"]) if item.get("updated_at") else now_now,
                )
                m.movie_genres = []
                for g_item in item.get("genres", []):
                    g = Genre(
                        id=g_item["id"],
                        name=g_item["name"],
                        description=g_item.get("description"),
                        created_at=datetime.fromisoformat(g_item["created_at"]) if g_item.get("created_at") else now_now,
                    )
                    mg = MovieGenre(
                        movie_id=item["id"],
                        genre_id=g_item["id"],
                        genre=g,
                    )
                    m.movie_genres.append(mg)
                movies.append(m)
            return movies, total

        # 2. On Cache Miss: Auto update statuses & Query DB
        await self.auto_update_movie_statuses()

        query = select(Movie).where(Movie.is_active == True)

        if status:
            query = query.where(Movie.status == status)
        if search:
            query = query.where(Movie.title.ilike(f"%{search}%"))
        if genre_id:
            query = query.join(MovieGenre).where(MovieGenre.genre_id == genre_id)

        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        # Fetch with pagination
        query = query.offset(pagination.offset).limit(pagination.limit)
        query = query.options(selectinload(Movie.movie_genres).selectinload(MovieGenre.genre))
        result = await self.db.execute(query)
        movies = list(result.scalars().all())

        # 3. Store in Redis Cache (TTL = 300s)
        now_utc = datetime.now(timezone.utc)
        cache_data = {
            "total": total,
            "items": [
                {
                    "id": m.id,
                    "title": m.title,
                    "description": m.description,
                    "poster_url": m.poster_url,
                    "duration_minutes": m.duration_minutes,
                    "release_date": m.release_date.isoformat() if m.release_date else None,
                    "language": m.language,
                    "tmdb_id": m.tmdb_id,
                    "status": m.status.value,
                    "rating": m.rating,
                    "director": m.director,
                    "is_active": m.is_active,
                    "created_at": m.created_at.isoformat() if getattr(m, "created_at", None) else now_utc.isoformat(),
                    "updated_at": m.updated_at.isoformat() if getattr(m, "updated_at", None) else now_utc.isoformat(),
                    "genres": [
                        {
                            "id": mg.genre.id,
                            "name": mg.genre.name,
                            "description": getattr(mg.genre, "description", None),
                            "created_at": mg.genre.created_at.isoformat() if getattr(mg.genre, "created_at", None) else now_utc.isoformat(),
                        }
                        for mg in m.movie_genres
                        if mg.genre
                    ],
                }
                for m in movies
            ],
        }
        await self.cache.set(cache_key, cache_data, ttl=300)

        return movies, total

    async def get_movie(self, movie_id: int) -> Movie:
        """Get single movie by ID (supports local ID and TMDB ID with dynamic auto-sync)."""
        # 1. Try to query locally by local ID or TMDB ID
        result = await self.db.execute(
            select(Movie)
            .where(((Movie.id == movie_id) | (Movie.tmdb_id == movie_id)) & (Movie.is_active == True))
            .options(selectinload(Movie.movie_genres).selectinload(MovieGenre.genre))
        )
        movie = result.scalar_one_or_none()
        if movie:
            return movie

        # 2. If not found locally, try to dynamically sync from TMDB API
        try:
            # Sync movie from TMDB (this saves it to database)
            movie = await self.sync_from_tmdb(movie_id)
            if movie:
                # Reload with genres relation populated
                result = await self.db.execute(
                    select(Movie)
                    .where(Movie.id == movie.id)
                    .options(selectinload(Movie.movie_genres).selectinload(MovieGenre.genre))
                )
                return result.scalar_one()
        except Exception as e:
            logger.warning("Dynamic TMDB sync on get_movie failed", tmdb_id=movie_id, error=str(e))

        raise NotFoundException("Movie", movie_id)

    async def create_movie(self, data: MovieCreate) -> Movie:
        """Create a new movie."""
        # Check duplicate TMDB ID
        if data.tmdb_id:
            existing = await self.db.execute(
                select(Movie).where(Movie.tmdb_id == data.tmdb_id)
            )
            if existing.scalar_one_or_none():
                raise ConflictException(f"Movie with TMDB ID {data.tmdb_id} already exists")

        movie = Movie(
            title=data.title,
            description=data.description,
            poster_url=data.poster_url,
            duration_minutes=data.duration_minutes,
            release_date=data.release_date,
            language=data.language,
            rating=data.rating,
            status=data.status,
            tmdb_id=data.tmdb_id,
            is_active=True,
        )
        self.db.add(movie)
        await self.db.flush()

        # Attach genres
        if data.genre_ids:
            await self._set_genres(movie.id, data.genre_ids)

        await self.db.refresh(movie)
        await self.cache.delete_pattern(f"{CACHE_KEY_MOVIES}*")
        logger.info("Movie created", movie_id=movie.id, title=movie.title)
        return movie

    async def update_movie(self, movie_id: int, data: MovieUpdate) -> Movie:
        """Update movie fields."""
        movie = await self.get_movie(movie_id)

        update_data = data.model_dump(exclude_unset=True, exclude={"genre_ids"})
        for field, value in update_data.items():
            if value is None and field in {"title", "status"}:
                continue
            setattr(movie, field, value)

        if data.genre_ids is not None:
            await self._set_genres(movie_id, data.genre_ids)

        await self.db.flush()
        await self.db.refresh(movie)
        await self.cache.delete_pattern(f"{CACHE_KEY_MOVIES}*")
        await self.cache.delete(CACHE_KEY_MOVIE.format(id=movie_id))
        logger.info("Movie updated", movie_id=movie_id)
        return movie

    async def delete_movie(self, movie_id: int) -> None:
        """Soft-delete a movie."""
        movie = await self.get_movie(movie_id)
        movie.is_active = False
        await self.db.flush()
        await self.cache.delete_pattern(f"{CACHE_KEY_MOVIES}*")
        await self.cache.delete(CACHE_KEY_MOVIE.format(id=movie_id))
        logger.info("Movie soft-deleted", movie_id=movie_id)

    async def sync_from_tmdb(self, tmdb_id: int, tmdb_data: Optional[Dict[str, Any]] = None) -> Movie:
        """Sync movie from TMDB API (supports pre-fetched tmdb_data)."""
        tmdb_service = TMDBService()
        if not tmdb_data:
            tmdb_data = await tmdb_service.get_movie(tmdb_id)

        # Check if already exists
        result = await self.db.execute(select(Movie).where(Movie.tmdb_id == tmdb_id))
        movie = result.scalar_one_or_none()
        inferred_status = self._infer_status_from_release_date(tmdb_data.get("release_date"))

        # Fallback poster lookup if primary TMDB poster_url is empty
        poster_url = tmdb_data.get("poster_url")
        if not poster_url and tmdb_data.get("title"):
            try:
                search_res = await tmdb_service.search_movies(tmdb_data["title"])
                for item in search_res.get("results", []):
                    if item.get("poster_url"):
                        poster_url = item["poster_url"]
                        break
            except Exception as e:
                logger.warning("Poster fallback search failed", title=tmdb_data["title"], error=str(e))

        if movie:
            # Update existing
            movie.title = tmdb_data["title"]
            movie.description = tmdb_data.get("overview")
            movie.poster_url = poster_url or movie.poster_url
            movie.duration_minutes = tmdb_data.get("runtime")
            movie.release_date = tmdb_data.get("release_date")
            movie.language = tmdb_data.get("original_language")
            movie.status = inferred_status
        else:
            # Create new
            movie = Movie(
                title=tmdb_data["title"],
                description=tmdb_data.get("overview"),
                poster_url=poster_url,
                duration_minutes=tmdb_data.get("runtime"),
                release_date=tmdb_data.get("release_date"),
                language=tmdb_data.get("original_language"),
                tmdb_id=tmdb_id,
                status=inferred_status,
                is_active=True,
            )
            self.db.add(movie)
            await self.db.flush()

        # Sync genres — map English/prefixed genre names to Vietnamese
        genre_names = tmdb_data.get("genres", [])
        genre_ids = []
        for raw_genre in genre_names:
            normalized_name = normalize_genre_name(raw_genre)
            # Case-insensitive lookup to prevent duplicates
            result = await self.db.execute(
                select(Genre).where(func.lower(Genre.name) == normalized_name.lower())
            )
            genre = result.scalar_one_or_none()
            if not genre:
                genre = Genre(name=normalized_name)
                self.db.add(genre)
                try:
                    await self.db.flush()
                except Exception:
                    # Another concurrent request inserted the same genre — fetch it
                    await self.db.rollback()
                    result = await self.db.execute(
                        select(Genre).where(func.lower(Genre.name) == normalized_name.lower())
                    )
                    genre = result.scalar_one_or_none()
                    if not genre:
                        raise
            genre_ids.append(genre.id)

        if genre_ids:
            await self._set_genres(movie.id, genre_ids)

        if self.cache:
            try:
                res = self.cache.delete_pattern(f"{CACHE_KEY_MOVIES}*")
                if hasattr(res, "__await__"):
                    await res
            except Exception:
                pass
        logger.info("Movie synced from TMDB", tmdb_id=tmdb_id, movie_id=movie.id)
        
        # Eager load relationships to avoid Pydantic lazy load errors during serialization
        result = await self.db.execute(
            select(Movie)
            .where(Movie.id == movie.id)
            .options(selectinload(Movie.movie_genres).selectinload(MovieGenre.genre))
        )
        return result.scalar_one()

    async def _set_genres(self, movie_id: int, genre_ids: List[int]) -> None:
        """Replace all genres for a movie."""
        await self.db.execute(delete(MovieGenre).where(MovieGenre.movie_id == movie_id))
        for genre_id in genre_ids:
            result = await self.db.execute(select(Genre).where(Genre.id == genre_id))
            if result.scalar_one_or_none():
                mg = MovieGenre(movie_id=movie_id, genre_id=genre_id)
                self.db.add(mg)
        await self.db.flush()
