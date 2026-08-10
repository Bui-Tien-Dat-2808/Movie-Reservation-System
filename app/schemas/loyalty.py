from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class PointTransactionResponse(BaseModel):
    id: int
    points: int
    reason: Optional[str] = None
    reservation_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LoyaltyStatusResponse(BaseModel):
    points: int
    tier: str
    tier_label: str
    tier_color: str
    tier_icon: str
    points_to_next_tier: int
    transactions: List[PointTransactionResponse]

    model_config = {"from_attributes": True}


class AdminPointAdjustRequest(BaseModel):
    user_id: int
    points: int
    reason: str
