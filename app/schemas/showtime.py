from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.showtime import ShowtimeStatus
from app.models.showtime_seat import SeatStatus
from app.schemas.movie import MovieListResponse
from app.schemas.room import RoomResponse, SeatResponse


class ShowtimeSeatResponse(BaseModel):
    id: int
    seat_id: int
    status: SeatStatus
    held_until: Optional[datetime] = None
    seat: SeatResponse

    model_config = {"from_attributes": True}


class SeatHoldRequest(BaseModel):
    seat_ids: List[int] = Field(..., min_length=1, max_length=10)


class SeatHoldResponse(BaseModel):
    showtime_id: int
    seat_ids: List[int]
    held_until: datetime


class ShowtimeBase(BaseModel):
    movie_id: int
    room_id: int
    start_time: datetime
    end_time: datetime
    base_price: Decimal = Field(..., gt=0)
    vip_price: Optional[Decimal] = Field(None, gt=0)

    @model_validator(mode="after")
    def validate_times(self) -> "ShowtimeBase":
        from datetime import timezone
        start = self.start_time.astimezone(timezone.utc) if self.start_time.tzinfo else self.start_time.replace(tzinfo=timezone.utc)
        end = self.end_time.astimezone(timezone.utc) if self.end_time.tzinfo else self.end_time.replace(tzinfo=timezone.utc)
        if end <= start:
            raise ValueError("end_time must be after start_time")
        return self


class ShowtimeCreate(ShowtimeBase):
    pass


class ShowtimeUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    base_price: Optional[Decimal] = Field(None, gt=0)
    vip_price: Optional[Decimal] = Field(None, gt=0)
    status: Optional[ShowtimeStatus] = None


class ShowtimeResponse(ShowtimeBase):
    id: int
    status: ShowtimeStatus
    movie: Optional[MovieListResponse] = None
    room: Optional[RoomResponse] = None
    available_seats: Optional[int] = None
    total_seats: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ShowtimeSeatMapResponse(BaseModel):
    showtime_id: int
    total_seats: int
    available_seats: int
    reserved_seats: int
    seats: List[ShowtimeSeatResponse]

    model_config = {"from_attributes": True}
