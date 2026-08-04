from typing import Any, Dict
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.dependencies import get_db, require_admin
from app.models.reservation import Reservation, ReservationStatus
from app.models.movie import Movie, MovieStatus
from app.models.room import Room
from app.models.user import User
from app.models.showtime import Showtime

router = APIRouter(prefix="/analytics", tags=["Analytics & Reports"])
logger = structlog.get_logger()

@router.get("/dashboard", summary="Get real live database analytics (Admin)")
async def get_dashboard_analytics(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Admin: Calculate real live analytics aggregated directly from PostgreSQL database.
    """
    # 1. Total Revenue from Confirmed Reservations
    rev_res = await db.execute(
        select(func.coalesce(func.sum(Reservation.total_price), 0)).where(
            Reservation.status == ReservationStatus.CONFIRMED
        )
    )
    total_revenue = float(rev_res.scalar() or 0)

    # 2. Total Confirmed Ticket/Reservation Count
    res_count_res = await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.status == ReservationStatus.CONFIRMED
        )
    )
    total_reservations = int(res_count_res.scalar() or 0)

    # 3. Active Movies Count
    active_movies_res = await db.execute(
        select(func.count(Movie.id)).where(Movie.status == MovieStatus.NOW_SHOWING)
    )
    active_movies_count = int(active_movies_res.scalar() or 0)

    # 4. Total Registered Users Count
    users_count_res = await db.execute(select(func.count(User.id)))
    total_users_count = int(users_count_res.scalar() or 0)

    # 5. Total Rooms Count
    rooms_count_res = await db.execute(select(func.count(Room.id)))
    total_rooms_count = int(rooms_count_res.scalar() or 0)

    # 6. Total Showtimes Count
    showtimes_count_res = await db.execute(select(func.count(Showtime.id)))
    total_showtimes_count = int(showtimes_count_res.scalar() or 0)

    return {
        "is_live_db": True,
        "total_revenue": total_revenue,
        "total_reservations": total_reservations,
        "active_movies_count": active_movies_count,
        "total_users_count": total_users_count,
        "total_rooms_count": total_rooms_count,
        "total_showtimes_count": total_showtimes_count,
    }
