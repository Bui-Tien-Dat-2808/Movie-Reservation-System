import enum
from typing import Optional
from datetime import datetime
from sqlalchemy import Enum, ForeignKey, Integer, UniqueConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SeatStatus(str, enum.Enum):
    AVAILABLE = "available"
    HELD = "held"
    BOOKED = "booked"
    MAINTENANCE = "maintenance"


class ShowtimeSeat(Base):
    """Tracks seat availability per showtime. Created when showtime is created."""
    __tablename__ = "showtime_seats"
    __table_args__ = (
        UniqueConstraint("showtime_id", "seat_id", name="uq_showtime_seat"),
    )

    showtime_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("showtimes.id", ondelete="CASCADE"), nullable=False
    )
    seat_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seats.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[SeatStatus] = mapped_column(
        Enum(SeatStatus), default=SeatStatus.AVAILABLE, nullable=False
    )
    held_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    held_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    showtime: Mapped["Showtime"] = relationship("Showtime", back_populates="showtime_seats")  # noqa: F821
    seat: Mapped["Seat"] = relationship("Seat", back_populates="showtime_seats")  # noqa: F821
    held_by_user: Mapped[Optional["User"]] = relationship("User")  # noqa: F821
    reservation_seat: Mapped["ReservationSeat"] = relationship(  # noqa: F821
        "ReservationSeat", back_populates="showtime_seat", uselist=False
    )

    def __repr__(self) -> str:
        return f"<ShowtimeSeat showtime={self.showtime_id} seat={self.seat_id} status={self.status}>"
