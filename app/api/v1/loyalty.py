from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.loyalty import AdminPointAdjustRequest, LoyaltyStatusResponse, PointTransactionResponse
from app.schemas.user import UserListResponse
from app.services.loyalty_service import LoyaltyService

router = APIRouter(prefix="/loyalty", tags=["Loyalty"])


@router.get("/me", response_model=LoyaltyStatusResponse)
async def get_my_loyalty(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await LoyaltyService.get_user_loyalty(db, current_user.id)


@router.get("/users", response_model=List[UserListResponse])
async def list_loyalty_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    q: str | None = Query(default=None),
):
    from app.models.user import UserRole
    from sqlalchemy import select

    query = select(User).where(User.role != UserRole.ADMIN).order_by(User.loyalty_points.desc(), User.id)
    if q:
        query = query.where(
            (User.full_name.ilike(f"%{q}%")) | (User.email.ilike(f"%{q}%"))
        )
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/adjust", response_model=PointTransactionResponse)
async def adjust_points(
    payload: AdminPointAdjustRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        tx = await LoyaltyService.adjust_points(db, payload.user_id, payload.points, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PointTransactionResponse(
        id=tx.id,
        points=tx.points,
        reason=tx.reason,
        reservation_id=tx.reservation_id,
        created_at=tx.created_at,
    )
