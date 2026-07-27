from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_redis, require_admin, get_current_user
from app.models.movie import MovieStatus
from app.schemas.common import PaginatedResponse
from app.schemas.movie import MovieCreate, MovieListResponse, MovieResponse, MovieUpdate
from app.services.cache_service import CacheService
from app.services.movie_service import MovieService
from app.services.tmdb_service import TMDBService
from app.utils.pagination import PaginationParams, paginate

router = APIRouter(prefix="/movies", tags=["Movies"])
logger = structlog.get_logger()


def get_movie_service(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> MovieService:
    return MovieService(db, CacheService(redis))


@router.get(
    "/",
    response_model=PaginatedResponse[MovieListResponse],
    summary="List movies",
)
async def list_movies(
    pagination: PaginationParams = Depends(),
    search: Optional[str] = Query(None, description="Search by title"),
    genre_id: Optional[int] = Query(None, description="Filter by genre"),
    status_filter: Optional[MovieStatus] = Query(None, alias="status"),
    service: MovieService = Depends(get_movie_service),
):
    """
    List movies with optional filtering:
    - Search by title
    - Filter by genre
    - Filter by status (now_showing, coming_soon, ended)
    """
    movies, total = await service.get_movies(pagination, genre_id, search, status_filter)
    return paginate(
        [MovieListResponse.model_validate(m) for m in movies],
        total,
        pagination.page,
        pagination.page_size,
    )


@router.get(
    "/now-showing",
    response_model=PaginatedResponse[MovieListResponse],
    summary="List now-showing movies (Public)",
)
async def list_now_showing(
    pagination: PaginationParams = Depends(),
    search: Optional[str] = Query(None, description="Search by title"),
    genre_id: Optional[int] = Query(None, description="Filter by genre"),
    service: MovieService = Depends(get_movie_service),
):
    """
    Public: Get all movies currently showing in theaters.
    No authentication required — accessible by guests, users, and admins.
    """
    movies, total = await service.get_movies(
        pagination, genre_id, search, status=MovieStatus.NOW_SHOWING
    )
    return paginate(
        [MovieListResponse.model_validate(m) for m in movies],
        total,
        pagination.page,
        pagination.page_size,
    )


@router.get("/{movie_id}", response_model=MovieResponse, summary="Get movie detail")
async def get_movie(
    movie_id: int,
    service: MovieService = Depends(get_movie_service),
):
    """Get detailed information about a specific movie."""
    return await service.get_movie(movie_id)


@router.post(
    "/",
    response_model=MovieResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create movie (Admin)",
)
async def create_movie(
    data: MovieCreate,
    service: MovieService = Depends(get_movie_service),
    _=Depends(require_admin),
):
    """Admin: create a new movie."""
    return await service.create_movie(data)


@router.put("/{movie_id}", response_model=MovieResponse, summary="Update movie (Admin)")
async def update_movie(
    movie_id: int,
    data: MovieUpdate,
    service: MovieService = Depends(get_movie_service),
    _=Depends(require_admin),
):
    """Admin: update movie information."""
    return await service.update_movie(movie_id, data)


@router.delete(
    "/{movie_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete movie (Admin)",
)
async def delete_movie(
    movie_id: int,
    service: MovieService = Depends(get_movie_service),
    _=Depends(require_admin),
):
    """Admin: soft-delete a movie."""
    await service.delete_movie(movie_id)


@router.post(
    "/tmdb/sync/{tmdb_id}",
    response_model=MovieResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync movie from TMDB (Admin)",
)
async def sync_from_tmdb(
    tmdb_id: int,
    service: MovieService = Depends(get_movie_service),
    _=Depends(require_admin),
):
    """
    Admin: sync a movie's data from The Movie Database (TMDB).
    Creates the movie if it doesn't exist, updates if it does.
    """
    return await service.sync_from_tmdb(tmdb_id)


@router.get(
    "/tmdb/search",
    summary="Search TMDB for movies (Admin)",
)
async def search_tmdb(
    query: str = Query(..., min_length=1, description="Search query"),
    page: int = Query(1, ge=1),
    _=Depends(require_admin),
):
    """Admin: search TMDB for movies to import."""
    tmdb_service = TMDBService()
    return await tmdb_service.search_movies(query, page)


@router.get(
    "/tmdb/popular",
    summary="Get popular movies from TMDB (Admin)",
)
async def get_tmdb_popular(
    page: int = Query(1, ge=1),
    _=Depends(require_admin),
):
    """Admin: get popular movies from TMDB."""
    tmdb_service = TMDBService()
    return await tmdb_service.get_popular_movies(page)


@router.get(
    "/tmdb/list/{list_id}",
    summary="Get movies from a TMDB list",
)
async def get_tmdb_list_movies(
    list_id: str,
    page: int = Query(1, ge=1),
    _=Depends(get_current_user),
):
    """Get movies from a TMDB list (Admin and Users)."""
    tmdb_service = TMDBService()
    return await tmdb_service.get_list_movies(list_id, page)
