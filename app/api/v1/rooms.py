import string
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db, require_admin
from app.models.seat import Seat, SeatType
from app.models.room import Room
from app.models.showtime import Showtime, ShowtimeStatus
from app.models.showtime_seat import ShowtimeSeat, SeatStatus
from app.schemas.room import (
    RoomCreate, RoomDetailResponse, RoomResponse, RoomUpdate,
    RoomStatusResponse, ActiveShowtimeInfo, SeatStatusItem,
)

router = APIRouter(prefix="/rooms", tags=["Rooms"])
logger = structlog.get_logger()


async def _generate_seats(db: AsyncSession, room: Room) -> None:
    """Auto-generate seats for a room based on rows x cols layout."""
    row_labels = list(string.ascii_uppercase)  # A-Z
    for row_idx in range(room.total_rows):
        row_label = row_labels[row_idx] if row_idx < 26 else f"A{row_idx - 25}"
        for col in range(1, room.total_cols + 1):
            # VIP seats in the middle rows
            is_vip_row = room.total_rows // 3 <= row_idx < 2 * room.total_rows // 3
            seat_type = SeatType.VIP if is_vip_row else SeatType.STANDARD
            seat = Seat(
                room_id=room.id,
                row_label=row_label,
                col_number=col,
                seat_type=seat_type,
                is_active=True,
            )
            db.add(seat)
    await db.flush()


from sqlalchemy import select, func as sqla_func
from app.models.room import Room, RoomType

@router.get("/", response_model=List[RoomResponse], summary="List all rooms")
async def list_rooms(
    room_type: Optional[RoomType] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get all active screening rooms."""
    query = select(Room).where(Room.is_active == True).options(selectinload(Room.seats))
    if room_type:
        query = query.where(Room.room_type == room_type)
    query = query.order_by(Room.room_type, Room.room_number)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{room_id}", response_model=RoomDetailResponse, summary="Get room with seat layout")
async def get_room(room_id: int, db: AsyncSession = Depends(get_db)):
    """Get room details including full seat layout."""
    result = await db.execute(
        select(Room)
        .where(Room.id == room_id)
        .options(selectinload(Room.seats))
    )
    room = result.scalar_one_or_none()
    if not room:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Room", room_id)
    return room


@router.get(
    "/{room_id}/status",
    response_model=RoomStatusResponse,
    summary="Get room occupancy status",
)
async def get_room_status(room_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get full occupancy status of a room:
    - Whether the room is currently in use
    - Current showtime (ONGOING): movie info, seat-by-seat status breakdown
    - Upcoming showtimes (SCHEDULED): list with seat availability
    """
    from app.core.exceptions import NotFoundException

    # Load room with seats
    result = await db.execute(
        select(Room).where(Room.id == room_id).options(selectinload(Room.seats))
    )
    room = result.scalar_one_or_none()
    if not room:
        raise NotFoundException("Room", room_id)

    # Load all non-cancelled showtimes for this room, eager-load movie & showtime_seats->seat
    st_result = await db.execute(
        select(Showtime)
        .where(
            Showtime.room_id == room_id,
            Showtime.status != ShowtimeStatus.CANCELLED,
        )
        .options(
            selectinload(Showtime.movie),
            selectinload(Showtime.showtime_seats).selectinload(ShowtimeSeat.seat),
        )
        .order_by(Showtime.start_time)
    )
    showtimes = st_result.scalars().all()

    now = datetime.now(timezone.utc)

    def _make_showtime_info(st: Showtime) -> ActiveShowtimeInfo:
        """Build ActiveShowtimeInfo from a Showtime ORM object."""
        seat_items: list[SeatStatusItem] = []
        counts = {SeatStatus.AVAILABLE: 0, SeatStatus.HELD: 0, SeatStatus.BOOKED: 0}

        for ss in st.showtime_seats:
            # Apply lazy expiration in-memory (held_until expired → treat as available)
            effective_status = ss.status
            if ss.status == SeatStatus.HELD and ss.held_until:
                held_until_aware = (
                    ss.held_until.replace(tzinfo=timezone.utc)
                    if ss.held_until.tzinfo is None
                    else ss.held_until.astimezone(timezone.utc)
                )
                if held_until_aware < now:
                    effective_status = SeatStatus.AVAILABLE

            counts[effective_status] = counts.get(effective_status, 0) + 1

            seat_items.append(SeatStatusItem(
                seat_id=ss.seat_id,
                label=f"{ss.seat.row_label}{ss.seat.col_number}" if ss.seat else str(ss.seat_id),
                seat_type=ss.seat.seat_type if ss.seat else SeatType.STANDARD,
                status=effective_status,
                held_until=ss.held_until if effective_status == SeatStatus.HELD else None,
            ))

        # Sort seats by label for readability
        seat_items.sort(key=lambda s: s.label)
        total = len(seat_items)

        return ActiveShowtimeInfo(
            showtime_id=st.id,
            movie_title=st.movie.title if st.movie else "Unknown",
            movie_poster_url=st.movie.poster_url if st.movie else None,
            status=st.status,
            start_time=st.start_time,
            end_time=st.end_time,
            base_price=st.base_price,
            vip_price=st.vip_price,
            total_seats=total,
            available_seats=counts.get(SeatStatus.AVAILABLE, 0),
            held_seats=counts.get(SeatStatus.HELD, 0),
            booked_seats=counts.get(SeatStatus.BOOKED, 0),
            seats=seat_items,
        )

    current_showtime = None
    upcoming_showtimes = []

    for st in showtimes:
        start = (
            st.start_time.replace(tzinfo=timezone.utc)
            if st.start_time.tzinfo is None
            else st.start_time.astimezone(timezone.utc)
        )
        end = (
            st.end_time.replace(tzinfo=timezone.utc)
            if st.end_time.tzinfo is None
            else st.end_time.astimezone(timezone.utc)
        )

        if start <= now < end:
            # Room is actively being used right now
            current_showtime = _make_showtime_info(st)
        elif start > now:
            # Scheduled for the future
            upcoming_showtimes.append(_make_showtime_info(st))

    is_in_use = current_showtime is not None

    return RoomStatusResponse(
        room_id=room.id,
        room_name=room.name,
        room_type=room.room_type,
        is_active=room.is_active,
        total_seats=room.total_seats,
        is_in_use=is_in_use,
        current_showtime=current_showtime,
        upcoming_showtimes=upcoming_showtimes,
    )



@router.post(
    "/",
    response_model=RoomDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create room (Admin)",
)
async def create_room(
    data: RoomCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Admin: create a new screening room.
    Seats are automatically generated based on total_rows × total_cols.
    Middle third rows will be VIP seats.
    """
    from app.core.exceptions import ConflictException

    # 1. Determine room_number if not provided
    room_number = data.room_number
    if not room_number:
        max_num_res = await db.execute(
            select(sqla_func.coalesce(sqla_func.max(Room.room_number), 0))
            .where(Room.room_type == data.room_type)
        )
        room_number = max_num_res.scalar_one() + 1

    # Check unique (room_type, room_number)
    existing_num = await db.execute(
        select(Room).where(Room.room_type == data.room_type, Room.room_number == room_number)
    )
    if existing_num.scalar_one_or_none():
        raise ConflictException(f"Phòng số {room_number} thuộc loại '{data.room_type.value}' đã tồn tại.")

    # 2. Determine room name if not provided
    name_label_map = {
        RoomType.STANDARD: "Standard",
        RoomType.VIP: "VIP",
        RoomType.IMAX: "IMAX",
        RoomType.THREE_D: "3D",
        RoomType.FOUR_D: "4DX",
        RoomType.KIDS: "Kids",
    }
    label = name_label_map.get(data.room_type, "Room")
    room_name = data.name.strip() if data.name and data.name.strip() else f"{label} {room_number}"

    # Check unique name
    existing_name = await db.execute(select(Room).where(Room.name == room_name))
    if existing_name.scalar_one_or_none():
        raise ConflictException(f"Phòng tên '{room_name}' đã tồn tại.")

    room = Room(
        name=room_name,
        room_type=data.room_type,
        room_number=room_number,
        description=data.description,
        total_rows=data.total_rows,
        total_cols=data.total_cols,
        is_active=True,
    )
    db.add(room)
    await db.flush()

    # Auto-generate seats
    await _generate_seats(db, room)

    await db.refresh(room)
    result = await db.execute(
        select(Room)
        .where(Room.id == room.id)
        .options(selectinload(Room.seats))
    )
    return result.scalar_one()


@router.put("/{room_id}", response_model=RoomResponse, summary="Update room (Admin)")
async def update_room(
    room_id: int,
    data: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Admin: update screening room details."""
    result = await db.execute(
        select(Room).where(Room.id == room_id).options(selectinload(Room.seats))
    )
    room = result.scalar_one_or_none()
    if not room:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Room", room_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is None and field in {"name", "room_type", "total_rows", "total_cols", "is_active"}:
            continue
        setattr(room, field, value)

    await db.flush()
    await db.refresh(room)
    return room


@router.delete("/{room_id}", summary="Delete room (Admin)")
async def delete_room(
    room_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """
    Admin: delete a screening room.
    Checks if there are active showtimes scheduled in this room.
    If active showtimes exist, raises error preventing deletion.
    If only past/cancelled showtimes exist, soft-deletes (is_active=False).
    If no showtimes exist, hard-deletes room and its seats.
    """
    from app.core.exceptions import NotFoundException, BadRequestException

    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise NotFoundException("Room", room_id)

    # Check for active non-cancelled showtimes
    st_res = await db.execute(
        select(Showtime).where(
            Showtime.room_id == room_id,
            Showtime.status != ShowtimeStatus.CANCELLED,
        )
    )
    active_showtimes = st_res.scalars().all()
    if active_showtimes:
        raise BadRequestException(
            f"Không thể xóa phòng '{room.name}' vì đang có {len(active_showtimes)} suất chiếu được xếp lịch. Vui lòng hủy các suất chiếu của phòng này trước."
        )

    # Check for historical showtimes
    hist_res = await db.execute(select(Showtime).where(Showtime.room_id == room_id))
    has_history = hist_res.scalars().first() is not None

    if has_history:
        room.is_active = False
        await db.flush()
        return {"message": f"Đã ẩn phòng '{room.name}' khỏi hệ thống."}
    else:
        await db.delete(room)
        await db.flush()
        return {"message": f"Đã xóa hoàn toàn phòng '{room.name}'."}
