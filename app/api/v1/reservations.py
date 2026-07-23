from typing import List

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_active_user, get_db, get_redis, require_admin
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.reservation import (
    ReservationCreate,
    ReservationListResponse,
    ReservationResponse,
    RevenueReportResponse,
    ShowtimeCapacityResponse,
)
from app.services.cache_service import CacheService
from app.services.reservation_service import ReservationService
from app.utils.pagination import PaginationParams, paginate

router = APIRouter(prefix="/reservations", tags=["Reservations"])
logger = structlog.get_logger()


def get_reservation_service(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> ReservationService:
    return ReservationService(db, CacheService(redis))


@router.get(
    "/",
    response_model=PaginatedResponse[ReservationResponse],
    summary="Get my reservations",
)
async def get_my_reservations(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    service: ReservationService = Depends(get_reservation_service),
):
    """Get all reservations for the current user."""
    reservations, total = await service.get_user_reservations(current_user.id, pagination)
    items = [_build_reservation_response(r) for r in reservations]
    return paginate(items, total, pagination.page, pagination.page_size)


@router.post(
    "/",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create reservation",
)
async def create_reservation(
    data: ReservationCreate,
    current_user: User = Depends(get_current_active_user),
    service: ReservationService = Depends(get_reservation_service),
):
    """
    Reserve seats for a showtime.

    - Provide showtime_id and a list of seat_ids
    - Seats must be available
    - Showtime must be in the future
    - Uses database locking to prevent overbooking
    """
    reservation = await service.create_reservation(current_user.id, data)
    return _build_reservation_response(reservation)


@router.get("/{reservation_id}", response_model=ReservationResponse, summary="Get reservation detail")
async def get_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_active_user),
    service: ReservationService = Depends(get_reservation_service),
):
    """Get details of a specific reservation (must be owned by current user)."""
    from app.models.user import UserRole
    user_id = None if current_user.role == UserRole.ADMIN else current_user.id
    reservation = await service.get_reservation(reservation_id, user_id)
    return _build_reservation_response(reservation)


@router.delete(
    "/{reservation_id}",
    status_code=status.HTTP_200_OK,
    response_model=ReservationResponse,
    summary="Cancel reservation",
)
async def cancel_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_active_user),
    service: ReservationService = Depends(get_reservation_service),
):
    """
    Cancel a reservation.
    - Only upcoming showtime reservations can be cancelled
    - Seats are freed up upon cancellation
    """
    reservation = await service.cancel_reservation(reservation_id, current_user.id)
    return _build_reservation_response(reservation)


# ─── Admin Endpoints ───────────────────────────────────────────────────────────

@router.get(
    "/admin/all",
    response_model=PaginatedResponse[ReservationResponse],
    summary="List all reservations (Admin)",
)
async def admin_list_all(
    pagination: PaginationParams = Depends(),
    service: ReservationService = Depends(get_reservation_service),
    _=Depends(require_admin),
):
    """Admin: get all reservations across all users."""
    reservations, total = await service.get_all_reservations(pagination)
    items = [_build_reservation_response(r) for r in reservations]
    return paginate(items, total, pagination.page, pagination.page_size)


@router.get(
    "/admin/report/revenue",
    response_model=RevenueReportResponse,
    summary="Revenue report (Admin)",
)
async def revenue_report(
    service: ReservationService = Depends(get_reservation_service),
    _=Depends(require_admin),
):
    """Admin: get overall revenue and reservation statistics."""
    return await service.get_revenue_report()


@router.get(
    "/admin/report/capacity",
    response_model=List[ShowtimeCapacityResponse],
    summary="Showtime capacity report (Admin)",
)
async def capacity_report(
    service: ReservationService = Depends(get_reservation_service),
    _=Depends(require_admin),
):
    """Admin: get per-showtime capacity and revenue data (last 50 showtimes)."""
    return await service.get_capacity_report()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_reservation_response(reservation) -> ReservationResponse:
    """Build reservation response with enriched seat data."""
    from app.schemas.reservation import ReservationSeatResponse

    seats = []
    for rs in reservation.reservation_seats:
        seat_data = {
            "id": rs.id,
            "showtime_seat_id": rs.showtime_seat_id,
            "price": rs.price,
        }
        if rs.showtime_seat and rs.showtime_seat.seat:
            seat = rs.showtime_seat.seat
            seat_data["seat_label"] = f"{seat.row_label}{seat.col_number}"
            seat_data["seat_type"] = seat.seat_type.value
            seat_data["row_label"] = seat.row_label
            seat_data["col_number"] = seat.col_number
        seats.append(ReservationSeatResponse(**seat_data))

    return ReservationResponse(
        id=reservation.id,
        showtime_id=reservation.showtime_id,
        user_id=reservation.user_id,
        total_price=reservation.total_price,
        status=reservation.status,
        notes=reservation.notes,
        reservation_seats=seats,
        created_at=reservation.created_at,
    )
