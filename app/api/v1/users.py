from typing import Optional

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_active_user, get_db, require_admin
from app.models.user import User, UserRole
from app.schemas.common import PaginatedResponse
from app.schemas.user import UserListResponse, UserResponse, UserUpdate
from app.utils.pagination import PaginationParams, paginate

router = APIRouter(prefix="/users", tags=["Users"])
logger = structlog.get_logger()


@router.get("/me", response_model=UserResponse, summary="Get my profile")
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Get the current logged-in user's profile."""
    return current_user


@router.put("/me", response_model=UserResponse, summary="Update my profile")
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's profile."""
    if data.full_name is not None:
        current_user.full_name = data.full_name
    if data.email is not None:
        # Check uniqueness
        from sqlalchemy import select
        existing = await db.execute(
            select(User).where(User.email == data.email, User.id != current_user.id)
        )
        if existing.scalar_one_or_none():
            from app.core.exceptions import ConflictException
            raise ConflictException("Email is already in use")
        current_user.email = data.email
    await db.flush()
    await db.refresh(current_user)
    return current_user


@router.get(
    "/",
    response_model=PaginatedResponse[UserListResponse],
    summary="List all users (Admin)",
)
async def list_users(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin: list all users with pagination."""
    from sqlalchemy import func
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    result = await db.execute(
        select(User)
        .offset(pagination.offset)
        .limit(pagination.limit)
        .order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return paginate(
        [UserListResponse.model_validate(u) for u in users],
        count,
        pagination.page,
        pagination.page_size,
    )


@router.patch(
    "/{user_id}/promote",
    response_model=UserResponse,
    summary="Promote user to admin (Admin)",
)
async def promote_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin: promote a user to admin role."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("User", user_id)

    user.role = UserRole.ADMIN
    await db.flush()
    await db.refresh(user)
    logger.info("User promoted to admin", user_id=user_id)
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate user (Admin)",
)
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    """Admin: deactivate a user account."""
    if user_id == current_admin.id:
        from app.core.exceptions import ValidationException
        raise ValidationException("Cannot deactivate your own account")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("User", user_id)

    user.is_active = False
    await db.flush()
    logger.info("User deactivated", user_id=user_id)
