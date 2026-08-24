from typing import Any, Dict, List
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, text
from sqlalchemy.orm import selectinload

from app.dependencies import get_db, require_admin
from app.models.reservation import Reservation, ReservationStatus
from app.models.movie import Movie, MovieStatus
from app.models.room import Room
from app.models.user import User
from app.models.showtime import Showtime
from app.models.showtime_seat import ShowtimeSeat, SeatStatus

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

    # 7. Real Monthly Revenue Aggregation (Grouped by YYYY-MM)
    month_select = text("to_char(created_at, 'YYYY-MM') AS month_key")
    month_group = text("to_char(created_at, 'YYYY-MM')")
    monthly_stmt = (
        select(
            month_select,
            func.coalesce(func.sum(Reservation.total_price), 0).label("revenue"),
            func.count(Reservation.id).label("tickets")
        )
        .where(Reservation.status == ReservationStatus.CONFIRMED)
        .group_by(month_group)
        .order_by(month_group)
    )
    monthly_res = await db.execute(monthly_stmt)
    monthly_rows = monthly_res.fetchall()

    monthly_revenue = [
        {
            "month": str(r[0]),
            "revenue": float(r[1]),
            "tickets": int(r[2]),
        }
        for r in monthly_rows
    ]

    # 8. Real Movie Revenue Breakdown (Grouped by Movie)
    movie_stmt = (
        select(
            Movie.id,
            Movie.title,
            func.coalesce(func.sum(Reservation.total_price), 0).label("revenue"),
            func.count(Reservation.id).label("tickets")
        )
        .join(Showtime, Reservation.showtime_id == Showtime.id)
        .join(Movie, Showtime.movie_id == Movie.id)
        .where(Reservation.status == ReservationStatus.CONFIRMED)
        .group_by(Movie.id, Movie.title)
        .order_by(desc("revenue"))
        .limit(6)
    )
    movie_res = await db.execute(movie_stmt)
    movie_rows = movie_res.fetchall()

    movie_revenue_breakdown = []
    for r in movie_rows:
        rev = float(r[2])
        pct = round((rev / total_revenue * 100), 1) if total_revenue > 0 else 0
        movie_revenue_breakdown.append({
            "movie_id": r[0],
            "movie_title": r[1],
            "revenue": rev,
            "tickets": int(r[3]),
            "percentage": pct,
        })

    # 9. Real Room Occupancy Rates
    rooms_stmt = select(Room).options(selectinload(Room.seats))
    rooms = (await db.execute(rooms_stmt)).scalars().all()

    room_occupancy = []
    for room in rooms:
        booked_st = select(func.count(ShowtimeSeat.id)).join(Showtime).where(
            Showtime.room_id == room.id,
            ShowtimeSeat.status == SeatStatus.BOOKED
        )
        booked_cnt = (await db.execute(booked_st)).scalar() or 0

        total_st = select(func.count(ShowtimeSeat.id)).join(Showtime).where(
            Showtime.room_id == room.id
        )
        total_cnt = (await db.execute(total_st)).scalar() or 0

        occ_rate = round((booked_cnt / total_cnt * 100), 1) if total_cnt > 0 else 0.0
        room_occupancy.append({
            "room_id": room.id,
            "room_name": room.name,
            "occupancy_rate": occ_rate,
            "total_seats": total_cnt,
            "booked_seats": booked_cnt,
        })

    # 10. Recent Transactions List
    recent_stmt = (
        select(Reservation)
        .where(Reservation.status == ReservationStatus.CONFIRMED)
        .order_by(Reservation.created_at.desc())
        .limit(5)
        .options(
            selectinload(Reservation.user),
            selectinload(Reservation.showtime).selectinload(Showtime.movie),
            selectinload(Reservation.showtime).selectinload(Showtime.room),
        )
    )
    recent_res = (await db.execute(recent_stmt)).scalars().all()
    recent_transactions = [
        {
            "id": r.id,
            "ticket_code": r.ticket_code or f"CVN-{r.id}",
            "customer_name": r.user.full_name if r.user else "Khách vãng lai",
            "movie_title": r.showtime.movie.title if (r.showtime and r.showtime.movie) else "N/A",
            "total_price": float(r.total_price),
            "payment_method": r.payment_method or "vnpay",
            "created_at": r.created_at.strftime("%d/%m/%Y %H:%M"),
        }
        for r in recent_res
    ]

    return {
        "is_live_db": True,
        "total_revenue": total_revenue,
        "total_reservations": total_reservations,
        "active_movies_count": active_movies_count,
        "total_users_count": total_users_count,
        "total_rooms_count": total_rooms_count,
        "total_showtimes_count": total_showtimes_count,
        "monthly_revenue": monthly_revenue,
        "movie_revenue_breakdown": movie_revenue_breakdown,
        "room_occupancy": room_occupancy,
        "recent_transactions": recent_transactions,
    }
