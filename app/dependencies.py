from typing import AsyncGenerator, Optional

import redis.asyncio as aioredis
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import verify_access_token
from app.db.session import AsyncSessionLocal
from app.models.user import UserRole

logger = structlog.get_logger()

# HTTP Bearer scheme
bearer_scheme = HTTPBearer(auto_error=False)


# ─── Database Dependency ───────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ─── Redis Dependency ──────────────────────────────────────────────────────────

_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """Provide a shared Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


# ─── Auth Dependencies ─────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Validate access token and return the current user."""
    from app.models.user import User
    from sqlalchemy import select

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    token_data = verify_access_token(credentials.credentials)
    if token_data is None:
        raise credentials_exception

    # Check blacklist (logout validation)
    from app.services.cache_service import CacheService
    cache = CacheService(redis)
    if await cache.is_access_token_blacklisted(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalidated (logged out)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    return user


async def get_current_active_user(current_user=Depends(get_current_user)):
    """Ensure user is active."""
    return current_user


async def require_admin(current_user=Depends(get_current_user)):
    """Require admin role."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Optional auth dependency returning None if not logged in."""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db, redis)
    except HTTPException:
        return None
