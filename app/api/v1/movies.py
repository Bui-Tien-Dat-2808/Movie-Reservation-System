import json
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_active_user, get_db, get_redis, require_admin
from app.models.movie import Movie, MovieStatus
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
    movie = await service.get_movie(movie_id)

    # Parse cast from DB column
    cast_data = None
    if getattr(movie, "cast_json", None):
        try:
            cast_data = json.loads(movie.cast_json)
        except Exception:
            cast_data = None

    # Build response with display fallbacks (no TMDB call here — service handles enrichment)
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
    - Determines NOW_SHOWING vs COMING_SOON based on active showtimes and release date.
    - Detailed error tracking per item.
    """
    import math
    import httpx
    from app.core.exceptions import ConflictException

    tmdb = TMDBService()
    if not tmdb.api_key or not tmdb.api_key.strip():
        raise ConflictException("TMDB_API_KEY chưa được cấu hình. Vui lòng thêm TMDB_API_KEY vào file .env.")

    pages_needed = max(1, math.ceil(limit / 20))

    # Delegate all sync logic to service layer; only handle HTTP-level errors here
    try:
        return await service.perform_auto_tmdb_sync(limit=limit, pages_needed=pages_needed)
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


@router.post(
    "/admin/backfill-trailers",
    summary="Admin: Backfill trailer/director/cast/rating còn thiếu từ TMDB",
)
async def backfill_trailers(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    _=Depends(require_admin),
):
    """Admin endpoint to safely backfill missing or corrupted trailers, directors, cast, and ratings from TMDB via ORM."""
    movie_service = MovieService(db, CacheService(redis))
    tmdb_service = TMDBService()

    result = await db.execute(
        select(Movie).where(
            Movie.is_active == True,
            or_(
                Movie.trailer_url.is_(None),
                ~Movie.trailer_url.like("https://www.youtube.com/embed/%"),
                Movie.director.is_(None),
                Movie.director.in_(["Đang cập nhật", "N/A", ""]),
                Movie.cast_json.is_(None),
                Movie.rating.is_(None),
            ),
        )
    )
    movies_to_fix = result.scalars().all()

    updated_count = 0
    errors = []

    for movie in movies_to_fix:
        try:
            # 1. Search TMDB if tmdb_id is missing
            if not movie.tmdb_id and movie.title:
                try:
                    search_res = await tmdb_service.search_movies(movie.title)
                    results = search_res.get("results", [])
                    if results:
                        movie.tmdb_id = results[0].get("tmdb_id") or results[0].get("id")
                except Exception as e:
                    logger.warning("Backfill TMDB title search failed", movie_id=movie.id, title=movie.title, error=str(e))

            # 2. Sync full details from TMDB if tmdb_id is available
            if movie.tmdb_id:
                try:
                    await movie_service.sync_from_tmdb(movie.tmdb_id)
                except Exception as e:
                    logger.warning("Backfill TMDB sync failed", movie_id=movie.id, tmdb_id=movie.tmdb_id, error=str(e))

            # 3. Ensure trailer_url is clean: if not a valid embed URL, set to None (avoids broken YouTube frames)
            if movie.trailer_url and not movie.trailer_url.startswith("https://www.youtube.com/embed/"):
                movie.trailer_url = None

            updated_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            errors.append({"movie_id": movie.id, "title": movie.title, "error": str(e)})

    await db.commit()
    try:
        await CacheService(redis).delete_pattern("movies:*")
    except Exception as e:
        logger.warning("Failed to clear movie cache after backfill", error=str(e))

    return {
        "success": True,
        "updated": updated_count,
        "total_checked": len(movies_to_fix),
        "errors": errors,
        "message": f"Đã hoàn tất bổ sung trailer, đạo diễn, diễn viên và độ tuổi cho {updated_count}/{len(movies_to_fix)} phim!",
    }
