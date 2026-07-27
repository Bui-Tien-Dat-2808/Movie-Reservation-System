from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_active_user, get_db, get_redis, require_admin
from app.schemas.common import PaginatedResponse
from app.schemas.showtime import (
    ShowtimeCreate,
    ShowtimeResponse,
    ShowtimeSeatMapResponse,
    ShowtimeUpdate,
    SeatHoldRequest,
    SeatHoldResponse,
)
from app.services.cache_service import CacheService
from app.services.showtime_service import ShowtimeService
from app.utils.pagination import PaginationParams, paginate

router = APIRouter(prefix="/showtimes", tags=["Showtimes"])
logger = structlog.get_logger()


def get_showtime_service(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> ShowtimeService:
    return ShowtimeService(db, CacheService(redis))


@router.get(
    "/",
    response_model=PaginatedResponse[ShowtimeResponse],
    summary="List showtimes",
)
async def list_showtimes(
    pagination: PaginationParams = Depends(),
    movie_id: Optional[int] = Query(None, description="Filter by movie"),
    room_id: Optional[int] = Query(None, description="Filter by screening room"),
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    service: ShowtimeService = Depends(get_showtime_service),
):
    """
    List showtimes with optional filters.
    Filter by movie, room, or specific date.
    """
    showtimes, total = await service.get_showtimes(pagination, movie_id, room_id, date)

    items = []
    for st in showtimes:
        available = sum(1 for s in st.showtime_seats if s.status.value == "available")
        total_s = len(st.showtime_seats)
        response = ShowtimeResponse.model_validate(st)
        response.available_seats = available
        response.total_seats = total_s
        items.append(response)

    return paginate(items, total, pagination.page, pagination.page_size)


@router.get("/{showtime_id}", response_model=ShowtimeResponse, summary="Get showtime detail")
async def get_showtime(
    showtime_id: int,
    service: ShowtimeService = Depends(get_showtime_service),
):
    """Get detailed information about a showtime including seat availability count."""
    st = await service.get_showtime(showtime_id)
    available = sum(1 for s in st.showtime_seats if s.status.value == "available")
    total_s = len(st.showtime_seats)
    response = ShowtimeResponse.model_validate(st)
    response.available_seats = available
    response.total_seats = total_s
    return response


@router.get(
    "/{showtime_id}/seats",
    response_model=ShowtimeSeatMapResponse,
    summary="Get showtime seat map",
)
async def get_seat_map(
    showtime_id: int,
    service: ShowtimeService = Depends(get_showtime_service),
    _=Depends(get_current_active_user),
):
    """
    Get the full seat availability map for a showtime.
    Shows which seats are available, reserved, or under maintenance.
    """
    seat_map = await service.get_seat_map(showtime_id)
    return ShowtimeSeatMapResponse(**seat_map)


@router.post(
    "/",
    response_model=ShowtimeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create showtime (Admin)",
)
async def create_showtime(
    data: ShowtimeCreate,
    service: ShowtimeService = Depends(get_showtime_service),
    _=Depends(require_admin),
):
    """
    Admin: create a new showtime.
    Automatically generates seat slots from the room's seat layout.
    Validates for time conflicts in the same room.
    """
    return await service.create_showtime(data)


@router.put("/{showtime_id}", response_model=ShowtimeResponse, summary="Update showtime (Admin)")
async def update_showtime(
    showtime_id: int,
    data: ShowtimeUpdate,
    service: ShowtimeService = Depends(get_showtime_service),
    _=Depends(require_admin),
):
    """Admin: update showtime details."""
    return await service.update_showtime(showtime_id, data)


@router.delete(
    "/{showtime_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel showtime (Admin)",
)
async def cancel_showtime(
    showtime_id: int,
    service: ShowtimeService = Depends(get_showtime_service),
    _=Depends(require_admin),
):
    """Admin: cancel a showtime."""
    await service.cancel_showtime(showtime_id)


@router.post(
    "/{showtime_id}/hold",
    response_model=SeatHoldResponse,
    summary="Hold seats temporarily (User)",
)
async def hold_seats(
    showtime_id: int,
    data: SeatHoldRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_active_user),
):
    """
    Temporarily hold seats for a showtime (10 minutes).
    Uses SELECT FOR UPDATE to prevent race conditions.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.models.showtime import Showtime, ShowtimeStatus
    from app.models.showtime_seat import ShowtimeSeat, SeatStatus
    from app.core.exceptions import NotFoundException, SeatUnavailableException, ShowtimePastException

    # 1. Validate showtime
    showtime = await db.get(Showtime, showtime_id)
    if not showtime or showtime.status == ShowtimeStatus.CANCELLED:
        raise NotFoundException("Showtime", showtime_id)

    # Ensure showtime is in the future
    if showtime.start_time.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise ShowtimePastException()

    # 2. Lock requested seats in a transaction
    result = await db.execute(
        select(ShowtimeSeat)
        .where(
            ShowtimeSeat.showtime_id == showtime_id,
            ShowtimeSeat.seat_id.in_(data.seat_ids),
        )
        .with_for_update()
    )
    locked_seats = result.scalars().all()

    if len(locked_seats) != len(data.seat_ids):
        missing = set(data.seat_ids) - {s.seat_id for s in locked_seats}
        raise NotFoundException(f"Seats {list(missing)} not found in this showtime")

    # 3. Check if all seats are available or hold expired
    now = datetime.now(timezone.utc)
    unavailable_seats = []
    for ss in locked_seats:
        is_available = (
            ss.status == SeatStatus.AVAILABLE or
            (ss.status == SeatStatus.HELD and ss.held_until is not None and 
             (ss.held_until.replace(tzinfo=timezone.utc) if ss.held_until.tzinfo is None else ss.held_until.astimezone(timezone.utc)) < now)
        )
        if not is_available:
            unavailable_seats.append(ss.seat_id)

    if unavailable_seats:
        raise SeatUnavailableException(unavailable_seats)

    # 4. Set hold
    held_until = now + timedelta(minutes=10)
    for ss in locked_seats:
        ss.status = SeatStatus.HELD
        ss.held_by = user.id
        ss.held_until = held_until

    await db.flush()
    return SeatHoldResponse(
        showtime_id=showtime_id,
        seat_ids=data.seat_ids,
        held_until=held_until,
    )
