import enum
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ConcessionCategory(str, enum.Enum):
    COMBO = "combo"
    POPCORN = "popcorn"
    DRINK = "drink"
    SNACK = "snack"
    FOOD = "food"


class Concession(Base):
    __tablename__ = "concessions"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="combo", nullable=False)
    size: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # S, M, L, XL — popcorn/drink only
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    reservation_concessions: Mapped[List["ReservationConcession"]] = relationship(
        "ReservationConcession", back_populates="concession", lazy="selectin"
    )


class ReservationConcession(Base):
    __tablename__ = "reservation_concessions"

    reservation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concession_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("concessions.id"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Relationships
    reservation: Mapped["Reservation"] = relationship(  # type: ignore[name-defined]
        "Reservation", back_populates="reservation_concessions"
    )
    concession: Mapped["Concession"] = relationship(
        "Concession", back_populates="reservation_concessions"
    )
