from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.room import RoomType
from app.models.seat import SeatType


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
