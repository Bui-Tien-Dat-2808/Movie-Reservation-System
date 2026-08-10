import enum
from typing import List, Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SeatType(str, enum.Enum):
    STANDARD = "standard"
    VIP = "vip"
    COUPLE = "couple"
    KIDS = "kids"


class Seat(Base):
    __tablename__ = "seats"

    room_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    row_label: Mapped[str] = mapped_column(String(5), nullable=False)     # e.g., "A", "B", "C"
    col_number: Mapped[int] = mapped_column(Integer, nullable=False)       # e.g., 1, 2, 3
    seat_type: Mapped[SeatType] = mapped_column(
        Enum(SeatType, values_callable=lambda x: [e.name for e in x]), default=SeatType.STANDARD, nullable=False
    )
    width: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1 for standard/VIP, 2 for Couple
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    room: Mapped["Room"] = relationship("Room", back_populates="seats")  # noqa: F821
    showtime_seats: Mapped[List["ShowtimeSeat"]] = relationship(  # noqa: F821
        "ShowtimeSeat", back_populates="seat"
    )

    @property
    def label(self) -> str:
        """Human-readable seat label e.g. A1, B5."""
        return f"{self.row_label}{self.col_number}"

    def __repr__(self) -> str:
        return f"<Seat id={self.id} label={self.label} type={self.seat_type}>"
