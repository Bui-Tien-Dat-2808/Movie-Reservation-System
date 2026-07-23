from typing import List, Optional

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

CACHE_KEY_MOVIES = "movies:list"
CACHE_KEY_MOVIE = "movies:detail:{id}"


class MovieService:
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache

    async def get_movies(
        self,
        pagination: PaginationParams,
        genre_id: Optional[int] = None,
        search: Optional[str] = None,
        status: Optional[MovieStatus] = None,
    ) -> tuple[List[Movie], int]:
        """List movies with filtering and pagination."""
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
        movies = result.scalars().all()

        return list(movies), total

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

    async def sync_from_tmdb(self, tmdb_id: int) -> Movie:
        """Sync movie from TMDB API."""
        tmdb_service = TMDBService()
        tmdb_data = await tmdb_service.get_movie(tmdb_id)

        # Check if already exists
        result = await self.db.execute(select(Movie).where(Movie.tmdb_id == tmdb_id))
        movie = result.scalar_one_or_none()

        if movie:
            # Update existing
            movie.title = tmdb_data["title"]
            movie.description = tmdb_data.get("overview")
            movie.poster_url = tmdb_data.get("poster_url")
            movie.duration_minutes = tmdb_data.get("runtime")
            movie.release_date = tmdb_data.get("release_date")
            movie.language = tmdb_data.get("original_language")
        else:
            # Create new
            movie = Movie(
                title=tmdb_data["title"],
                description=tmdb_data.get("overview"),
                poster_url=tmdb_data.get("poster_url"),
                duration_minutes=tmdb_data.get("runtime"),
                release_date=tmdb_data.get("release_date"),
                language=tmdb_data.get("original_language"),
                tmdb_id=tmdb_id,
                is_active=True,
            )
            self.db.add(movie)
            await self.db.flush()

        # Sync genres
        genre_names = tmdb_data.get("genres", [])
        genre_ids = []
        for genre_name in genre_names:
            result = await self.db.execute(select(Genre).where(Genre.name == genre_name))
            genre = result.scalar_one_or_none()
            if not genre:
                genre = Genre(name=genre_name)
                self.db.add(genre)
                await self.db.flush()
            genre_ids.append(genre.id)

        if genre_ids:
            await self._set_genres(movie.id, genre_ids)

        await self.db.flush()
        await self.db.refresh(movie)
        await self.cache.delete_pattern(f"{CACHE_KEY_MOVIES}*")
        logger.info("Movie synced from TMDB", tmdb_id=tmdb_id, movie_id=movie.id)
        return movie

    async def _set_genres(self, movie_id: int, genre_ids: List[int]) -> None:
        """Replace all genres for a movie."""
        await self.db.execute(delete(MovieGenre).where(MovieGenre.movie_id == movie_id))
        for genre_id in genre_ids:
            result = await self.db.execute(select(Genre).where(Genre.id == genre_id))
            if result.scalar_one_or_none():
                mg = MovieGenre(movie_id=movie_id, genre_id=genre_id)
                self.db.add(mg)
        await self.db.flush()
