import string
from typing import List

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db, require_admin
from app.models.seat import Seat, SeatType
from app.models.room import Room
from app.schemas.room import RoomCreate, RoomDetailResponse, RoomResponse, RoomUpdate

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


@router.get("/", response_model=List[RoomResponse], summary="List all rooms")
async def list_rooms(db: AsyncSession = Depends(get_db)):
    """Get all active screening rooms."""
    result = await db.execute(
        select(Room)
        .where(Room.is_active == True)
        .options(selectinload(Room.seats))
        .order_by(Room.name)
    )
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
    # Check unique name
    existing = await db.execute(select(Room).where(Room.name == data.name))
    if existing.scalar_one_or_none():
        from app.core.exceptions import ConflictException
        raise ConflictException(f"Room '{data.name}' already exists")

    room = Room(
        name=data.name,
        room_type=data.room_type,
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
        setattr(room, field, value)

    await db.flush()
    await db.refresh(room)
    return room
