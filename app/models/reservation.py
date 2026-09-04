import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReservationStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXCHANGED = "exchanged"


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        Index("ix_reservations_user_status_created", "user_id", "status", "created_at"),
        Index("ix_reservations_showtime_status", "showtime_id", "status"),
    )

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
        Enum(ReservationStatus), default=ReservationStatus.PENDING, nullable=False
    )
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    exchanged_from_reservation_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="reservations")  # noqa: F821
    showtime: Mapped["Showtime"] = relationship("Showtime", back_populates="reservations")  # noqa: F821
    exchanged_from_reservation: Mapped[Optional["Reservation"]] = relationship(
        "Reservation", remote_side="Reservation.id", foreign_keys=[exchanged_from_reservation_id]
    )
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
    payment_transactions: Mapped[List["PaymentTransaction"]] = relationship(  # noqa: F821
        "PaymentTransaction",
        back_populates="reservation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    refund_transactions: Mapped[List["RefundTransaction"]] = relationship(  # noqa: F821
        "RefundTransaction",
        back_populates="reservation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def payment_method(self) -> str:
        if self.payment_transactions:
            # Ưu tiên transaction thành công
            for tx in self.payment_transactions:
                if getattr(tx, "status", None) == "success":
                    return tx.payment_method
            # Ưu tiên transaction tiền mặt
            for tx in self.payment_transactions:
                if getattr(tx, "payment_method", None) == "cash":
                    return "cash"
            # Fallback transaction gần nhất
            if len(self.payment_transactions) > 0:
                return self.payment_transactions[-1].payment_method
        if self.notes and "tiền mặt" in str(self.notes).lower():
            return "cash"
        return "vnpay"

    def __repr__(self) -> str:
        return f"<Reservation id={self.id} user={self.user_id} status={self.status}>"


class ReservationSeat(Base):
    """Individual seat within a reservation."""
    __tablename__ = "reservation_seats"

    reservation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False
    )
    showtime_seat_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("showtime_seats.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Relationships
    reservation: Mapped["Reservation"] = relationship(
        "Reservation", back_populates="reservation_seats"
    )
    showtime_seat: Mapped["ShowtimeSeat"] = relationship(  # noqa: F821
        "ShowtimeSeat", back_populates="reservation_seats"
    )

    def __repr__(self) -> str:
        return f"<ReservationSeat id={self.id} reservation={self.reservation_id}>"
