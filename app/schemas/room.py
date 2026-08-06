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
    width: int = 1
    label: str

    model_config = {"from_attributes": True}


class RoomBase(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    room_type: RoomType = RoomType.STANDARD
    room_number: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None
    total_rows: int = Field(10, gt=0, le=30)
    total_cols: int = Field(15, gt=0, le=50)
    has_couple_seats: bool = Field(True, description="Enable couple seats in the back row")
    couple_rows_count: int = Field(1, ge=0, le=3, description="Number of couple seat rows at the back")


class RoomCreate(RoomBase):
    pass


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    room_type: Optional[RoomType] = None
    room_number: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RoomResponse(RoomBase):
    id: int
    name: str
    room_number: Optional[int] = 1
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
