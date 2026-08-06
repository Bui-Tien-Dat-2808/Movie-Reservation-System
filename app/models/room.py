import enum
from typing import List, Optional

from sqlalchemy import Boolean, Enum, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RoomType(str, enum.Enum):
    STANDARD = "standard"
    IMAX = "imax"
    VIP = "vip"
    KIDS = "kids"
    THREE_D = "3d"
    FOUR_D = "4d"


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("room_type", "room_number", name="uq_rooms_type_number"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    room_type: Mapped[RoomType] = mapped_column(
        Enum(RoomType), default=RoomType.STANDARD, nullable=False
    )
    room_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    total_cols: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    seats: Mapped[List["Seat"]] = relationship(
        "Seat", back_populates="room", cascade="all, delete-orphan"
    )
    showtimes: Mapped[List["Showtime"]] = relationship(  # noqa: F821
        "Showtime", back_populates="room"
    )

    @property
    def total_seats(self) -> int:
        return self.total_rows * self.total_cols

    def __repr__(self) -> str:
        return f"<Room id={self.id} name={self.name} type={self.room_type}>"
