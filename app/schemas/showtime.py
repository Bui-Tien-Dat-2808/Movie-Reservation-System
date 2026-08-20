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
    couple_price: Optional[Decimal] = Field(None, gt=0)

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
    couple_price: Optional[Decimal] = Field(None, gt=0)
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


class AutoScheduleRequest(BaseModel):
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    movie_ids: Optional[List[int]] = None
    room_ids: Optional[List[int]] = None
    start_time_str: str = Field("08:00", description="HH:MM format e.g. 08:00")
    end_time_str: str = Field("23:30", description="HH:MM format e.g. 23:30")
    start_hour: Optional[int] = Field(8, ge=0, le=23)
    end_hour: Optional[int] = Field(23, ge=0, le=23)
    buffer_minutes: int = Field(15, ge=0, le=60)
    base_price: Decimal = Field(Decimal("90000"), gt=0)
    vip_price: Decimal = Field(Decimal("120000"), gt=0)
    couple_price: Optional[Decimal] = Field(Decimal("180000"), gt=0)
    replace_existing: bool = True
    smart_genre_matching: bool = True
    auto_pricing_by_room_type: bool = True
    stagger_interval_minutes: int = Field(15, ge=0, le=60)


class ProposedShowtimeItem(BaseModel):
    movie_id: int
    movie_title: str
    room_id: int
    room_name: str
    room_type: Optional[str] = "standard"
    matched_genre: Optional[str] = None
    start_time: datetime
    end_time: datetime
    base_price: Decimal
    vip_price: Decimal
    couple_price: Optional[Decimal] = None


class AutoScheduleConfirmRequest(BaseModel):
    showtimes: List[ProposedShowtimeItem]
    replace_existing: bool = True
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    room_ids: Optional[List[int]] = None


class BulkCancelShowtimesRequest(BaseModel):
    showtime_ids: Optional[List[int]] = None
    movie_id: Optional[int] = None
    room_id: Optional[int] = None
    only_upcoming: bool = True
