from datetime import date
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_active_user, get_db, get_redis, require_admin
from app.models.movie import Movie, MovieStatus
from app.models.showtime import Showtime
from app.schemas.common import PaginatedResponse
from app.schemas.movie import MovieCreate, MovieResponse, MovieUpdate
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
    "/now-showing",
    response_model=PaginatedResponse[MovieResponse],
    summary="List currently showing movies",
)
async def list_now_showing(
    pagination: PaginationParams = Depends(),
    search: Optional[str] = Query(None, description="Filter by title search"),
    service: MovieService = Depends(get_movie_service),
):
    """Public: List currently showing movies in theaters."""
    movies, total = await service.get_movies(
        pagination, status=MovieStatus.NOW_SHOWING, search=search
    )
    return paginate(movies, total, pagination.page, pagination.page_size)


@router.get(
    "/coming-soon",
    response_model=PaginatedResponse[MovieResponse],
    summary="List coming soon movies",
)
async def list_coming_soon(
    pagination: PaginationParams = Depends(),
    service: MovieService = Depends(get_movie_service),
):
    """Public: List upcoming movies that will be released soon."""
    movies, total = await service.get_movies(pagination, status=MovieStatus.COMING_SOON)
    return paginate(movies, total, pagination.page, pagination.page_size)


@router.get(
    "/",
    response_model=PaginatedResponse[MovieResponse],
    summary="List all movies",
)
async def list_movies(
    pagination: PaginationParams = Depends(),
    genre_id: Optional[int] = Query(None, description="Filter by genre"),
    search: Optional[str] = Query(None, description="Filter by title search"),
    status: Optional[MovieStatus] = Query(None, description="Filter by movie status"),
    service: MovieService = Depends(get_movie_service),
):
    """Public: List movies with optional filters by genre, status, or search query."""
    movies, total = await service.get_movies(
        pagination, genre_id=genre_id, search=search, status=status
    )
    return paginate(movies, total, pagination.page, pagination.page_size)


@router.get(
    "/{movie_id}",
    response_model=MovieResponse,
    summary="Get movie detail",
)
async def get_movie(
    movie_id: int,
    service: MovieService = Depends(get_movie_service),
):
    """Public: Get detailed information about a movie by ID (supports local ID or TMDB ID)."""
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
    """Admin: Create a new movie manually."""
    return await service.create_movie(data)


@router.put(
    "/{movie_id}",
    response_model=MovieResponse,
    summary="Update movie (Admin)",
)
async def update_movie(
    movie_id: int,
    data: MovieUpdate,
    service: MovieService = Depends(get_movie_service),
    _=Depends(require_admin),
):
    """Admin: Update movie details."""
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
    """Admin: Soft-delete a movie."""
    await service.delete_movie(movie_id)


@router.post(
    "/tmdb/sync/{tmdb_id}",
    response_model=MovieResponse,
    summary="Sync movie from TMDB (Admin)",
)
async def sync_tmdb_movie(
    tmdb_id: int,
    service: MovieService = Depends(get_movie_service),
    _=Depends(require_admin),
):
    """Admin: Fetch and import/update a movie from TMDB API by TMDB ID."""
    return await service.sync_from_tmdb(tmdb_id)


@router.get(
    "/tmdb/popular",
    summary="Get popular movies from TMDB (Admin)",
)
async def get_tmdb_popular(
    page: int = Query(1, ge=1),
    _=Depends(require_admin),
):
    """Admin: Get popular movies from TMDB."""
    tmdb_service = TMDBService()
    return await tmdb_service.get_popular_movies(page)


@router.post(
    "/tmdb/auto-sync",
    summary="Auto-sync Now Showing & Upcoming movies from TMDB (Admin)",
)
async def auto_sync_tmdb(
    limit: int = Query(12, ge=1, le=50, description="Number of movies per category"),
    service: MovieService = Depends(get_movie_service),
    _=Depends(require_admin),
):
    """
    Admin: Automatically fetch and import currently showing AND coming soon movies from TMDB API.
    - Dynamically scans N pages from TMDB until limit N items are retrieved.
    - Determines NOW_SHOWING vs COMING_SOON based on active showtimes and release date (<= today = NOW_SHOWING, > today = COMING_SOON).
    - Detailed error tracking per item.
    """
    import math
    import httpx
    from app.core.exceptions import ConflictException

    tmdb = TMDBService()
    pages_needed = max(1, math.ceil(limit / 20))

    now_playing_list = []
    upcoming_list = []
    failed_items = []

    # Catch network/connection errors specifically
    try:
        for p in range(1, pages_needed + 1):
            np_res = await tmdb.get_now_playing_movies(page=p)
            now_playing_list.extend(np_res.get("results", []))
            if p > np_res.get("total_pages", 1):
                break

        for p in range(1, pages_needed + 2):
            up_res = await tmdb.get_upcoming_movies(page=p)
            upcoming_list.extend(up_res.get("results", []))
            if p > up_res.get("total_pages", 1):
                break
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        logger.error("TMDB API HTTP error during auto-sync", status_code=status_code, response=e.response.text)
        if status_code == 401:
            raise ConflictException("TMDB API Key không hợp lệ hoặc đã bị thu hồi (Lỗi 401 Unauthorized). Vui lòng kiểm tra lại TMDB_API_KEY trong file .env.")
        elif status_code == 429:
            raise ConflictException("TMDB API bị vượt quá giới hạn lượt gọi (Lỗi 429 Too Many Requests). Vui lòng đợi vài phút và thử lại.")
        else:
            raise ConflictException(f"Lỗi phản hồi từ máy chủ TMDB (HTTP {status_code}). Vui lòng thử lại sau.")
    except httpx.HTTPError as e:
        logger.error("TMDB API Connection failed during auto-sync", error=str(e))
        raise ConflictException(
            "Không thể kết nối đến máy chủ TMDB API (Lỗi kết nối mạng). Vui lòng kiểm tra lại đường truyền mạng hoặc thử lại sau ít phút."
        )

    # Fetch movie IDs with active showtimes
    st_res = await service.db.execute(select(Showtime.movie_id).distinct())
    showtime_movie_ids = set(st_res.scalars().all())

    today = date.today()

    added_new_count = 0
    updated_existing_count = 0

    # 1. Sync Now Playing
    now_synced = 0
    for item in now_playing_list:
        if now_synced >= limit:
            break
        try:
            existing_res = await service.db.execute(
                select(Movie).where(Movie.tmdb_id == item["tmdb_id"])
            )
            ex = existing_res.scalar_one_or_none()
            if not ex:
                added_new_count += 1
            else:
                updated_existing_count += 1

            movie = await service.sync_from_tmdb(item["tmdb_id"])
            movie.status = MovieStatus.NOW_SHOWING
            now_synced += 1
        except Exception as e:
            logger.warning("Failed to sync now_playing movie", tmdb_id=item["tmdb_id"], error=str(e))
            failed_items.append({"tmdb_id": item["tmdb_id"], "title": item.get("title"), "reason": str(e)})

    # 2. Sync Upcoming Movies
    upcoming_synced = 0
    for item in upcoming_list:
        if upcoming_synced >= limit:
            break
        try:
            rel_date_str = item.get("release_date")
            rel_d = date.fromisoformat(rel_date_str) if rel_date_str else None

            existing_res = await service.db.execute(
                select(Movie).where(Movie.tmdb_id == item["tmdb_id"])
            )
            ex_movie = existing_res.scalar_one_or_none()

            if ex_movie and ex_movie.id in showtime_movie_ids:
                ex_movie.status = MovieStatus.NOW_SHOWING
                continue

            if rel_d and rel_d <= today:
                if ex_movie:
                    ex_movie.status = MovieStatus.NOW_SHOWING
                continue

            if not ex_movie:
                added_new_count += 1
            else:
                updated_existing_count += 1

            movie = await service.sync_from_tmdb(item["tmdb_id"])
            movie.status = MovieStatus.COMING_SOON
            upcoming_synced += 1
        except Exception as e:
            logger.warning("Failed to sync upcoming movie", tmdb_id=item["tmdb_id"], error=str(e))
            failed_items.append({"tmdb_id": item["tmdb_id"], "title": item.get("title"), "reason": str(e)})

    await service.db.commit()

    # Recalculate totals in database
    now_res = await service.db.execute(
        select(Movie).where((Movie.status == MovieStatus.NOW_SHOWING) & (Movie.is_active == True))
    )
    total_now = len(now_res.scalars().all())

    coming_res = await service.db.execute(
        select(Movie).where((Movie.status == MovieStatus.COMING_SOON) & (Movie.is_active == True))
    )
    total_coming = len(coming_res.scalars().all())

    return {
        "success": True,
        "added_new_count": added_new_count,
        "updated_existing_count": updated_existing_count,
        "total_now_showing": total_now,
        "total_coming_soon": total_coming,
        "failed_items": failed_items,
        "message": f"Đã đồng bộ tự động thành công từ TMDB API: Thêm mới {added_new_count} phim, cập nhật {updated_existing_count} phim. Hiện có {total_now} phim Đang Chiếu và {total_coming} phim Sắp Ra Mắt!",
    }


@router.get(
    "/tmdb/list/{list_id}",
    summary="Get movies from a TMDB list",
)
async def get_tmdb_list(
    list_id: str,
    page: int = Query(1, ge=1),
    _=Depends(require_admin),
):
    """Admin: Get movies from a specific TMDB list."""
    tmdb_service = TMDBService()
    return await tmdb_service.get_list_movies(list_id, page)
