import enum

from sqlalchemy import Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SeatStatus(str, enum.Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
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

    # Relationships
    showtime: Mapped["Showtime"] = relationship("Showtime", back_populates="showtime_seats")  # noqa: F821
    seat: Mapped["Seat"] = relationship("Seat", back_populates="showtime_seats")  # noqa: F821
    reservation_seat: Mapped["ReservationSeat"] = relationship(  # noqa: F821
        "ReservationSeat", back_populates="showtime_seat", uselist=False
    )

    def __repr__(self) -> str:
        return f"<ShowtimeSeat showtime={self.showtime_id} seat={self.seat_id} status={self.status}>"
