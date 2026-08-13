from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RefundTransaction(Base):
    __tablename__ = "refund_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    reservation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payment_transactions.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    vnp_request_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    # Statuses: pending | processing | success | failed | manual_required

    vnpay_response_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    vnpay_response_message: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    admin_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    resolved_by_admin_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    reservation: Mapped["Reservation"] = relationship("Reservation", back_populates="refund_transactions")  # noqa: F821
    payment_transaction: Mapped["PaymentTransaction"] = relationship("PaymentTransaction")  # noqa: F821
    resolved_by_admin: Mapped[Optional["User"]] = relationship("User", foreign_keys=[resolved_by_admin_id])  # noqa: F821

    def __repr__(self) -> str:
        return f"<RefundTransaction id={self.id} request_id={self.vnp_request_id} status={self.status}>"
