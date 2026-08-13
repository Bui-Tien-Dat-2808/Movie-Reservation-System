import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import bearer_scheme, get_current_user, get_db, get_redis
from app.schemas.auth import (
    AccessTokenResponse,
    ChangePasswordRequest,
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


async def check_rate_limit(redis_client, key: str, max_requests: int = 5, window_seconds: int = 60):
    """
    Rate limit helper enforcing max_requests per window_seconds using Redis.
    Safely skips if redis_client is mock or unavailable.
    """
    if not redis_client:
        return
    try:
        current = await redis_client.get(key)
        if current and not callable(current) and isinstance(current, (str, bytes, int)):
            if int(current) >= max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Quá nhiều yêu cầu đăng nhập/đăng ký. Vui lòng thử lại sau 1 phút.",
                )
        await redis_client.incr(key)
        await redis_client.expire(key, window_seconds)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Rate limit check skipped/failed", error=str(e))


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
    """Register a new user account with rate limiting."""
    await check_rate_limit(redis, f"ratelimit:register:{data.email}")
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
    await check_rate_limit(redis, f"ratelimit:login:{data.account}")
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


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change password and reset must_change_password flag",
)
async def change_password(
    data: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Change current user's password."""
    service = AuthService(db, CacheService(redis))
    await service.change_password(current_user.id, data.old_password, data.new_password)
    return {"message": "Mật khẩu đã được thay đổi thành công."}
