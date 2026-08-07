from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.reservation import ReservationStatus
from app.schemas.concession import ConcessionOrderItem, ReservationConcessionResponse


class ShowtimeSummary(BaseModel):
    """Lightweight showtime info embedded in reservation responses."""
    id: int
    movie_title: Optional[str] = None
    movie_poster_url: Optional[str] = None
    room_name: Optional[str] = None
    start_time: datetime
    end_time: datetime

    model_config = {"from_attributes": True}


class ReservationSeatResponse(BaseModel):
    id: int
    showtime_seat_id: int
    price: Decimal
    seat_label: Optional[str] = None
    seat_type: Optional[str] = None
    row_label: Optional[str] = None
    col_number: Optional[int] = None

    model_config = {"from_attributes": True}


class ReservationCreate(BaseModel):
    showtime_id: int
    seat_ids: List[int] = Field(..., min_length=1, max_length=10)
    voucher_code: Optional[str] = None
    concession_orders: Optional[List[ConcessionOrderItem]] = []


class ReservationExchangeRequest(BaseModel):
    new_showtime_id: int
    new_seat_ids: List[int] = Field(..., min_length=1, max_length=10)


class ReservationResponse(BaseModel):
    id: int
    showtime_id: int
    user_id: int
    ticket_code: Optional[str] = None
    total_price: Decimal
    voucher_code: Optional[str] = None
    discount_amount: Decimal = Decimal("0.00")
    status: ReservationStatus
    is_used: bool = False
    checked_in_at: Optional[datetime] = None
    notes: Optional[str] = None
    reservation_seats: List[ReservationSeatResponse] = []
    reservation_concessions: List[ReservationConcessionResponse] = []
    showtime: Optional[ShowtimeSummary] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReservationListResponse(BaseModel):
    id: int
    showtime_id: int
    ticket_code: Optional[str] = None
    total_price: Decimal
    voucher_code: Optional[str] = None
    discount_amount: Decimal = Decimal("0.00")
    status: ReservationStatus
    seat_count: int = 0
    showtime: Optional[ShowtimeSummary] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# Admin Reporting Schemas

class RevenueReportResponse(BaseModel):
    total_revenue: Decimal
    total_reservations: int
    confirmed_reservations: int
    cancelled_reservations: int
    average_revenue_per_reservation: Decimal


class ShowtimeCapacityResponse(BaseModel):
    showtime_id: int
    movie_title: str
    room_name: str
    start_time: datetime
    total_seats: int
    reserved_seats: int
    available_seats: int
    occupancy_rate: float
    revenue: Decimal
