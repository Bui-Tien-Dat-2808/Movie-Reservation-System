from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    reservation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), default="vnpay", nullable=False)
    vnp_txn_ref: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    transaction_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bank_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    response_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)  # pending, success, failed
    pay_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    reservation: Mapped["Reservation"] = relationship("Reservation", back_populates="payment_transactions")  # noqa: F821

    def __repr__(self) -> str:
        return f"<PaymentTransaction id={self.id} ref={self.vnp_txn_ref} status={self.status}>"
