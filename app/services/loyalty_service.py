from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loyalty import PointTransaction
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User


class LoyaltyService:
    TIERS = {
        "bronze": {"label": "Đồng", "color": "#CD7F32", "icon": "🥉", "min": 0},
        "silver": {"label": "Bạc", "color": "#A8A9AD", "icon": "🥈", "min": 1000},
        "gold": {"label": "Vàng", "color": "#FFD700", "icon": "🥇", "min": 5000},
        "diamond": {"label": "Kim Cương", "color": "#B9F2FF", "icon": "💎", "min": 10000},
    }

    @classmethod
    def calculate_tier(cls, points: int) -> str:
        if points >= cls.TIERS["diamond"]["min"]:
            return "diamond"
        if points >= cls.TIERS["gold"]["min"]:
            return "gold"
        if points >= cls.TIERS["silver"]["min"]:
            return "silver"
        return "bronze"

    @classmethod
    def points_to_next_tier(cls, points: int) -> int:
        tier = cls.calculate_tier(points)
        if tier == "bronze":
            return max(0, cls.TIERS["silver"]["min"] - points)
        if tier == "silver":
            return max(0, cls.TIERS["gold"]["min"] - points)
        if tier == "gold":
            return max(0, cls.TIERS["diamond"]["min"] - points)
        return 0

    @classmethod
    def tier_info(cls, points: int) -> dict:
        tier = cls.calculate_tier(points)
        return {
            "tier": tier,
            "label": cls.TIERS[tier]["label"],
            "color": cls.TIERS[tier]["color"],
            "icon": cls.TIERS[tier]["icon"],
            "points_to_next_tier": cls.points_to_next_tier(points),
        }

    @classmethod
    async def award_points(cls, db: AsyncSession, reservation: Reservation) -> None:
        """Award points to user when a reservation is confirmed. Prevents duplicate awards."""
        if reservation.status != ReservationStatus.CONFIRMED:
            return

        # Check if points were already awarded for this reservation
        existing_tx_result = await db.execute(
            select(PointTransaction).where(
                PointTransaction.reservation_id == reservation.id,
                PointTransaction.user_id == reservation.user_id,
                PointTransaction.points > 0,
            )
        )
        if existing_tx_result.scalar_one_or_none():
            return  # Already awarded

        user_result = await db.execute(select(User).where(User.id == reservation.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return

        total_price = reservation.total_price or 0
        points = int(total_price // 1000)
        if points <= 0:
            return

        user.loyalty_points = (user.loyalty_points or 0) + points
        user.loyalty_tier = cls.calculate_tier(user.loyalty_points)

        transaction = PointTransaction(
            user_id=user.id,
            reservation_id=reservation.id,
            points=points,
            reason="booking",
            created_at=datetime.now(timezone.utc),
        )
        db.add(transaction)
        await db.flush()

    @classmethod
    async def revoke_points(cls, db: AsyncSession, reservation: Reservation) -> None:
        """Revoke awarded points when a reservation is cancelled or refunded."""
        awarded_tx_result = await db.execute(
            select(PointTransaction).where(
                PointTransaction.reservation_id == reservation.id,
                PointTransaction.user_id == reservation.user_id,
                PointTransaction.points > 0,
            )
        )
        awarded_tx = awarded_tx_result.scalar_one_or_none()
        if not awarded_tx:
            return  # No points awarded to revoke

        # Check if already revoked
        revoked_tx_result = await db.execute(
            select(PointTransaction).where(
                PointTransaction.reservation_id == reservation.id,
                PointTransaction.user_id == reservation.user_id,
                PointTransaction.points < 0,
            )
        )
        if revoked_tx_result.scalar_one_or_none():
            return  # Already revoked

        user_result = await db.execute(select(User).where(User.id == reservation.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return

        points_to_revoke = awarded_tx.points
        user.loyalty_points = max(0, (user.loyalty_points or 0) - points_to_revoke)
        user.loyalty_tier = cls.calculate_tier(user.loyalty_points)

        transaction = PointTransaction(
            user_id=user.id,
            reservation_id=reservation.id,
            points=-points_to_revoke,
            reason="refund",
            created_at=datetime.now(timezone.utc),
        )
        db.add(transaction)
        await db.flush()

    @classmethod
    async def adjust_points(cls, db: AsyncSession, user_id: int, points: int, reason: str) -> PointTransaction:
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError("User not found")

        user.loyalty_points = max(0, (user.loyalty_points or 0) + points)
        user.loyalty_tier = cls.calculate_tier(user.loyalty_points)

        transaction = PointTransaction(
            user_id=user.id,
            reservation_id=None,
            points=points,
            reason=reason,
            created_at=datetime.now(timezone.utc),
        )
        db.add(transaction)
        await db.flush()
        await db.refresh(transaction)
        return transaction

    @classmethod
    async def get_user_loyalty(cls, db: AsyncSession, user_id: int) -> dict:
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError("User not found")

        tx_result = await db.execute(
            select(PointTransaction)
            .where(PointTransaction.user_id == user_id)
            .order_by(PointTransaction.created_at.desc())
        )
        transactions = tx_result.scalars().all()
        info = cls.tier_info(user.loyalty_points or 0)
        return {
            "points": user.loyalty_points or 0,
            "tier": info["tier"],
            "tier_label": info["label"],
            "tier_color": info["color"],
            "tier_icon": info["icon"],
            "points_to_next_tier": info["points_to_next_tier"],
            "transactions": [
                {
                    "id": tx.id,
                    "points": tx.points,
                    "reason": tx.reason,
                    "reservation_id": tx.reservation_id,
                    "created_at": tx.created_at.isoformat() if tx.created_at else None,
                }
                for tx in transactions
            ],
        }
