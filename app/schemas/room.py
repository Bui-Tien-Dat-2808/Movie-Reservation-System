from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.room import RoomType
from app.models.seat import SeatType
from app.models.showtime import ShowtimeStatus
from app.models.showtime_seat import SeatStatus


class SeatResponse(BaseModel):
    id: int
    row_label: str
    col_number: int
    seat_type: SeatType
    label: str

    model_config = {"from_attributes": True}


class RoomBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    room_type: RoomType = RoomType.STANDARD
    description: Optional[str] = None
    total_rows: int = Field(..., gt=0, le=30)
    total_cols: int = Field(..., gt=0, le=50)


class RoomCreate(RoomBase):
    pass


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    room_type: Optional[RoomType] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RoomResponse(RoomBase):
    id: int
    is_active: bool
    total_seats: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RoomDetailResponse(RoomResponse):
    seats: List[SeatResponse] = []

    model_config = {"from_attributes": True}


# ─── Room Status Endpoint ────────────────────────────────────────────────────

class SeatStatusItem(BaseModel):
    """Status of a single seat within a showtime."""
    seat_id: int
    label: str                   # e.g. "A3"
    seat_type: SeatType
    status: SeatStatus
    held_until: Optional[datetime] = None   # only set when status=held

    model_config = {"from_attributes": True}


class ActiveShowtimeInfo(BaseModel):
    """Showtime currently occupying the room."""
    showtime_id: int
    movie_title: str
    movie_poster_url: Optional[str] = None
    status: ShowtimeStatus
    start_time: datetime
    end_time: datetime
    base_price: Decimal
    vip_price: Optional[Decimal] = None
    total_seats: int
    available_seats: int
    held_seats: int
    booked_seats: int
    seats: List[SeatStatusItem] = []

    model_config = {"from_attributes": True}


class RoomStatusResponse(BaseModel):
    """Full occupancy status of a room — current and upcoming showtimes."""
    room_id: int
    room_name: str
    room_type: RoomType
    is_active: bool
    total_seats: int
    is_in_use: bool                                   # True if any non-cancelled showtime right now
    current_showtime: Optional[ActiveShowtimeInfo] = None   # showtime happening right now (ONGOING)
    upcoming_showtimes: List[ActiveShowtimeInfo] = []       # SCHEDULED showtimes in the future

    model_config = {"from_attributes": True}
