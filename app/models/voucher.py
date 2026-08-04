from datetime import date, datetime, timezone
import enum
from typing import List, Optional
from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class VoucherDiscountType(str, enum.Enum):
    PERCENT = "percent"
    FIXED = "fixed"


class Voucher(Base):
    __tablename__ = "vouchers"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    discount_type: Mapped[VoucherDiscountType] = mapped_column(
        Enum(VoucherDiscountType), default=VoucherDiscountType.PERCENT, nullable=False
    )
    discount_value: Mapped[float] = mapped_column(Float, nullable=False)
    min_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_weekdays: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # e.g. [2] for Wednesday (0=Mon)
    is_first_booking_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_uses_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_uses_per_user: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    redemptions: Mapped[List["VoucherRedemption"]] = relationship(
        "VoucherRedemption", back_populates="voucher", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Voucher id={self.id} code={self.code}>"


class VoucherRedemption(Base):
    __tablename__ = "voucher_redemptions"

    voucher_id: Mapped[int] = mapped_column(Integer, ForeignKey("vouchers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id: Mapped[int] = mapped_column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    voucher: Mapped["Voucher"] = relationship("Voucher", back_populates="redemptions")

    def __repr__(self) -> str:
        return f"<VoucherRedemption id={self.id} voucher_id={self.voucher_id} user_id={self.user_id}>"
