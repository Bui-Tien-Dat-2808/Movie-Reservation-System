import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_redis, bearer_scheme
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.user import UserCreate, UserResponse
from app.services.auth_service import AuthService
from app.services.cache_service import CacheService

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = structlog.get_logger()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
)
async def register(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Register a new user account."""
    service = AuthService(db, CacheService(redis))
    user = await service.register(data)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and get tokens",
)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Authenticate with email/password and receive:
    - **access_token**: short-lived JWT (30 min)
    - **refresh_token**: long-lived token (7 days)
    """
    service = AuthService(db, CacheService(redis))
    return await service.login(data)


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Refresh access token",
)
async def refresh_token(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Use refresh token to get a new access token."""
    service = AuthService(db, CacheService(redis))
    access_token = await service.refresh_access_token(data.refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (blacklist refresh token)",
)
async def logout(
    data: LogoutRequest,
    current_user=Depends(get_current_user),
    credentials=Depends(bearer_scheme),
    redis=Depends(get_redis),
):
    """Logout by blacklisting the refresh token and current access token."""
    service = AuthService(None, CacheService(redis))
    access_token = credentials.credentials if credentials else None
    await service.logout(current_user.id, data.refresh_token, access_token)
