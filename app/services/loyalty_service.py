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

    @staticmethod
    def points_to_next_tier(points: int) -> int:
        tier = LoyaltyService.calculate_tier(points)
        if tier == "bronze":
            return max(0, 1000 - points)
        if tier == "silver":
            return max(0, 5000 - points)
        if tier == "gold":
            return max(0, 10000 - points)
        return 0

    @staticmethod
    def tier_info(points: int) -> dict:
        tier = LoyaltyService.calculate_tier(points)
        return {
            "tier": tier,
            "label": LoyaltyService.TIERS[tier]["label"],
            "color": LoyaltyService.TIERS[tier]["color"],
            "icon": LoyaltyService.TIERS[tier]["icon"],
            "points_to_next_tier": LoyaltyService.points_to_next_tier(points),
        }

    @classmethod
    async def award_points(cls, db: AsyncSession, reservation: Reservation) -> None:
        if reservation.status != ReservationStatus.CONFIRMED:
            return

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
        await db.commit()

    @classmethod
    async def adjust_points(cls, db: AsyncSession, user_id: int, points: int, reason: str) -> PointTransaction:
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError("User not found")

        user.loyalty_points = (user.loyalty_points or 0) + points
        user.loyalty_tier = LoyaltyService.calculate_tier(user.loyalty_points)

        transaction = PointTransaction(
            user_id=user.id,
            reservation_id=None,
            points=points,
            reason=reason,
            created_at=datetime.now(timezone.utc),
        )
        db.add(transaction)
        await db.commit()
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
