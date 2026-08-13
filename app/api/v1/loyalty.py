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
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await LoyaltyService.get_user_loyalty(db, current_user.id, start_date, end_date)


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
    users = list(result.scalars().all())

    # Sync loyalty_tier for each user
    for u in users:
        pts = u.loyalty_points or 0
        u.loyalty_tier = LoyaltyService.calculate_tier(pts)
    return users


@router.get("/users/{user_id}", response_model=LoyaltyStatusResponse)
async def get_user_loyalty_detail(
    user_id: int,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        return await LoyaltyService.get_user_loyalty(db, user_id, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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
