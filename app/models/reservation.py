import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReservationStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXCHANGED = "exchanged"


class Reservation(Base):
    __tablename__ = "reservations"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    showtime_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("showtimes.id", ondelete="CASCADE"), nullable=False
    )
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    ticket_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True, index=True)
    voucher_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus), default=ReservationStatus.CONFIRMED, nullable=False
    )
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="reservations")  # noqa: F821
    showtime: Mapped["Showtime"] = relationship("Showtime", back_populates="reservations")  # noqa: F821
    reservation_seats: Mapped[List["ReservationSeat"]] = relationship(
        "ReservationSeat",
        back_populates="reservation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    reservation_concessions: Mapped[List["ReservationConcession"]] = relationship(  # noqa: F821
        "ReservationConcession",
        back_populates="reservation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


    def __repr__(self) -> str:
        return f"<Reservation id={self.id} user={self.user_id} status={self.status}>"


class ReservationSeat(Base):
    """Individual seat within a reservation."""
    __tablename__ = "reservation_seats"

    reservation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False
    )
    showtime_seat_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("showtime_seats.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Relationships
    reservation: Mapped["Reservation"] = relationship(
        "Reservation", back_populates="reservation_seats"
    )
    showtime_seat: Mapped["ShowtimeSeat"] = relationship(  # noqa: F821
        "ShowtimeSeat", back_populates="reservation_seat"
    )

    def __repr__(self) -> str:
        return f"<ReservationSeat id={self.id} reservation={self.reservation_id}>"
