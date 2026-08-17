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
    "/ended",
    response_model=PaginatedResponse[MovieResponse],
    summary="List ended movies",
)
async def list_ended(
    pagination: PaginationParams = Depends(),
    search: Optional[str] = Query(None, description="Filter by title search"),
    service: MovieService = Depends(get_movie_service),
):
    """Public: List movies that have ended their theatrical run."""
    movies, total = await service.get_movies(
        pagination, status=MovieStatus.ENDED, search=search
    )
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


from urllib.parse import quote_plus
import json


@router.get(
    "/{movie_id}",
    response_model=MovieResponse,
    summary="Get movie detail",
)
async def get_movie(
    movie_id: int,
    service: MovieService = Depends(get_movie_service),
    db: AsyncSession = Depends(get_db),
):
    """Public: Get detailed information about a movie by ID (supports local ID or TMDB ID)."""
    movie = await service.get_movie(movie_id)

    # 1. Parse cast from DB column if available
    cast_data = None
    if getattr(movie, "cast_json", None):
        try:
            cast_data = json.loads(movie.cast_json)
        except Exception:
            cast_data = None

    # 2. Only call TMDB if database is actually missing critical data!
    need_director = not movie.director or movie.director.strip() in ("", "Đang cập nhật", "N/A")
    need_cast = not cast_data
    need_trailer = movie.trailer_url is None

    if movie.tmdb_id and (need_director or need_cast or need_trailer):
        try:
            tmdb_service = TMDBService()
            # Calling get_movie fetches release_dates, videos, and credits in ONE single request!
            tmdb_data = await tmdb_service.get_movie(movie.tmdb_id)
            need_commit = False

            if need_director and tmdb_data.get("director"):
                movie.director = tmdb_data["director"]
                need_commit = True

            if need_cast and tmdb_data.get("cast"):
                cast_data = tmdb_data["cast"]
                movie.cast_json = json.dumps(cast_data, ensure_ascii=False)
                need_commit = True

            if need_trailer and tmdb_data.get("trailer_url"):
                movie.trailer_url = tmdb_data["trailer_url"]
                need_commit = True

            if need_commit:
                await db.commit()
                await db.refresh(movie)
        except Exception as e:
            logger.warning("Failed to resolve TMDB details for movie", movie_id=movie_id, error=str(e))

    # 3. Clean fallbacks (NO YouTube search URL fallback)
    trailer_url = getattr(movie, "trailer_url", None)
    director = movie.director
    if not director or director.strip() in ("", "Đang cập nhật", "N/A"):
        director = "Đang cập nhật"

    description = movie.description
    if not description or not description.strip():
        description = "Nội dung bộ phim đang được cập nhật. Vui lòng theo dõi thêm thông tin chi tiết."

    movie_resp = MovieResponse.model_validate(movie)
    movie_resp.trailer_url = trailer_url
    movie_resp.director = director
    movie_resp.description = description
    if cast_data:
        movie_resp.cast = cast_data

    return movie_resp


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
    if not tmdb.api_key or not tmdb.api_key.strip():
        raise ConflictException("TMDB_API_KEY chưa được cấu hình. Vui lòng thêm TMDB_API_KEY vào file .env.")

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

    # Extract target items up to limit
    target_now_playing = now_playing_list[:limit]
    target_upcoming = upcoming_list[:limit]

    # Collect all unique TMDB IDs needed
    all_tmdb_ids = list({item["tmdb_id"] for item in (target_now_playing + target_upcoming)})

    # Pre-fetch all movie details from TMDB API concurrently in parallel (max 8 concurrent connections)
    import asyncio
    semaphore = asyncio.Semaphore(8)
    prefetched_data = {}
    fetch_errors = {}

    async def fetch_detail(tmdb_id: int):
        async with semaphore:
            try:
                detail = await tmdb.get_movie(tmdb_id)
                prefetched_data[tmdb_id] = detail
            except Exception as e:
                fetch_errors[tmdb_id] = str(e)

    if all_tmdb_ids:
        await asyncio.gather(*(fetch_detail(tid) for tid in all_tmdb_ids))

    # 1. Sync Now Playing
    for item in target_now_playing:
        tmdb_id = item["tmdb_id"]
        if tmdb_id in fetch_errors:
            failed_items.append({"tmdb_id": tmdb_id, "title": item.get("title"), "reason": fetch_errors[tmdb_id]})
            continue

        try:
            existing_res = await service.db.execute(
                select(Movie).where(Movie.tmdb_id == tmdb_id)
            )
            ex = existing_res.scalar_one_or_none()
            if not ex:
                added_new_count += 1
            else:
                updated_existing_count += 1

            movie = await service.sync_from_tmdb(tmdb_id, prefetched_data.get(tmdb_id))
            if movie.id in showtime_movie_ids:
                movie.status = MovieStatus.NOW_SHOWING
            elif movie.release_date and movie.release_date > today:
                movie.status = MovieStatus.COMING_SOON
            else:
                movie.status = MovieStatus.NOW_SHOWING
        except Exception as e:
            logger.warning("Failed to sync now_playing movie", tmdb_id=tmdb_id, error=str(e))
            failed_items.append({"tmdb_id": tmdb_id, "title": item.get("title"), "reason": str(e)})

    # 2. Sync Upcoming Movies
    for item in target_upcoming:
        tmdb_id = item["tmdb_id"]
        if tmdb_id in fetch_errors and tmdb_id not in prefetched_data:
            failed_items.append({"tmdb_id": tmdb_id, "title": item.get("title"), "reason": fetch_errors[tmdb_id]})
            continue

        try:
            existing_res = await service.db.execute(
                select(Movie).where(Movie.tmdb_id == tmdb_id)
            )
            ex_movie = existing_res.scalar_one_or_none()

            if not ex_movie:
                added_new_count += 1
            else:
                updated_existing_count += 1

            movie = await service.sync_from_tmdb(tmdb_id, prefetched_data.get(tmdb_id))

            # Upcoming movies fetched from TMDB /upcoming endpoint are COMING_SOON
            # unless the cinema has active showtimes scheduled for them
            if movie.id in showtime_movie_ids:
                movie.status = MovieStatus.NOW_SHOWING
            elif movie.release_date and movie.release_date > today:
                movie.status = MovieStatus.COMING_SOON
            else:
                movie.status = MovieStatus.NOW_SHOWING
        except Exception as e:
            logger.warning("Failed to sync upcoming movie", tmdb_id=tmdb_id, error=str(e))
            failed_items.append({"tmdb_id": tmdb_id, "title": item.get("title"), "reason": str(e)})

    # Run general showtime-based status updates
    await service.auto_update_movie_statuses()

    await service.db.commit()

    # Invalidate stale Redis movie cache so new trailers and movie details are instantly served
    try:
        await service.cache.delete_pattern("movies:*")
    except Exception as e:
        logger.warning("Failed to invalidate movie cache after auto-sync", error=str(e))

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
