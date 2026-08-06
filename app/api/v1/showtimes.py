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
    AutoScheduleRequest,
    ProposedShowtimeItem,
    AutoScheduleConfirmRequest,
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
    upcoming_only: bool = Query(False, description="Exclude past showtimes that already started"),
    service: ShowtimeService = Depends(get_showtime_service),
):
    """
    List showtimes with optional filters.
    Filter by movie, room, or specific date.
    """
    items, total = await service.get_showtimes(pagination, movie_id, room_id, date, upcoming_only=upcoming_only)
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
    "/admin/auto-schedule/preview",
    response_model=list[ProposedShowtimeItem],
    summary="Preview auto-scheduled showtimes (Admin)",
)
async def preview_auto_schedule(
    data: AutoScheduleRequest,
    service: ShowtimeService = Depends(get_showtime_service),
    _=Depends(require_admin),
):
    """Admin: Generate preview of auto-scheduled showtimes without saving."""
    return await service.generate_auto_schedule_preview(data)


@router.post(
    "/admin/auto-schedule/confirm",
    status_code=status.HTTP_201_CREATED,
    summary="Confirm and bulk save auto-scheduled showtimes (Admin)",
)
async def confirm_auto_schedule(
    data: AutoScheduleConfirmRequest,
    service: ShowtimeService = Depends(get_showtime_service),
    _=Depends(require_admin),
):
    """Admin: Bulk insert approved proposed showtimes into DB."""
    count = await service.confirm_auto_schedule(
        data.showtimes,
        replace_existing=data.replace_existing,
    )
    return {"message": f"Successfully created {count} showtimes", "count": count}


@router.delete(
    "/admin/bulk-cancel",
    summary="Bulk cancel showtimes (Admin)",
)
async def bulk_cancel_showtimes(
    movie_id: Optional[int] = Query(None, description="Filter by movie ID"),
    room_id: Optional[int] = Query(None, description="Filter by room ID"),
    service: ShowtimeService = Depends(get_showtime_service),
    _=Depends(require_admin),
):
    """Admin: Bulk cancel all showtimes (or showtimes matching movie/room filter)."""
    count = await service.bulk_cancel_showtimes(movie_id, room_id)
    return {"message": f"Successfully cancelled {count} showtimes", "count": count}


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

    Uses SELECT FOR UPDATE to prevent race conditions:
    - If two users request the same last seat simultaneously, PostgreSQL serializes
      the lock. The second user will see the seat as HELD after the first commits,
      and receive a 409 SEAT_UNAVAILABLE response with a clear error message.
    - A user may re-hold seats they already hold (extends the hold by 10 minutes).
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

    # 2. Lock requested ShowtimeSeats with SELECT FOR UPDATE.
    #    This serializes concurrent requests for the same seat:
    #    the second request blocks here until the first transaction commits,
    #    then reads the updated status (HELD) and correctly raises 409.
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

    # 3. After acquiring the lock, re-evaluate each seat's true status.
    now = datetime.now(timezone.utc)
    booked_seats = []
    held_by_others = []

    for ss in locked_seats:
        if ss.status == SeatStatus.BOOKED:
            # Already purchased — cannot hold
            booked_seats.append(ss.seat_id)
        elif ss.status == SeatStatus.HELD:
            held_until_aware = (
                ss.held_until.replace(tzinfo=timezone.utc)
                if ss.held_until and ss.held_until.tzinfo is None
                else (ss.held_until.astimezone(timezone.utc) if ss.held_until else None)
            )
            hold_still_active = held_until_aware and held_until_aware > now
            held_by_someone_else = ss.held_by != user.id

            if hold_still_active and held_by_someone_else:
                # Another user is actively holding this seat right now
                held_by_others.append(ss.seat_id)
            # If held_by == user.id  → allow re-hold (extends the hold timer)
            # If hold has expired    → treat as AVAILABLE, allow hold

    # Build descriptive error combining all unavailable seats
    if booked_seats or held_by_others:
        parts = []
        if booked_seats:
            parts.append(f"Seats {booked_seats} are already booked")
        if held_by_others:
            parts.append(
                f"Seats {held_by_others} are currently held by another user — "
                "please try again in a few minutes"
            )
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail="; ".join(parts),
            headers={"X-Error-Code": "SEAT_UNAVAILABLE"},
        )

    # 4. All seats are either AVAILABLE or already held by this user — set / extend hold
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
