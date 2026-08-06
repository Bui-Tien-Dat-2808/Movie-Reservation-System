import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ShowtimeStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Showtime(Base):
    __tablename__ = "showtimes"

    movie_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False
    )
    room_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    vip_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    couple_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[ShowtimeStatus] = mapped_column(
        Enum(ShowtimeStatus), default=ShowtimeStatus.SCHEDULED, nullable=False
    )

    # Relationships
    movie: Mapped["Movie"] = relationship("Movie", back_populates="showtimes")  # noqa: F821
    room: Mapped["Room"] = relationship("Room", back_populates="showtimes")  # noqa: F821
    showtime_seats: Mapped[List["ShowtimeSeat"]] = relationship(  # noqa: F821
        "ShowtimeSeat",
        back_populates="showtime",
        cascade="all, delete-orphan",
    )
    reservations: Mapped[List["Reservation"]] = relationship(  # noqa: F821
        "Reservation", back_populates="showtime"
    )

    def __repr__(self) -> str:
        return f"<Showtime id={self.id} movie_id={self.movie_id} start={self.start_time}>"
