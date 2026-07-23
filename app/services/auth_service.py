import structlog
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import (
    ConflictException,
    InvalidCredentialsException,
    NotFoundException,
    TokenExpiredException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_refresh_token,
)
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserCreate
from app.services.cache_service import CacheService

logger = structlog.get_logger()


class AuthService:
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache

    async def register(self, data: UserCreate) -> User:
        """Register a new user."""
        # Check email uniqueness
        result = await self.db.execute(select(User).where(User.email == data.email))
        if result.scalar_one_or_none():
            raise ConflictException(f"Email '{data.email}' is already registered")

        user = User(
            email=data.email,
            hashed_password=get_password_hash(data.password),
            full_name=data.full_name,
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        logger.info("User registered", user_id=user.id, email=user.email)
        return user

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Authenticate user and return tokens."""
        result = await self.db.execute(select(User).where(User.email == data.email))
        user = result.scalar_one_or_none()

        if not user or not verify_password(data.password, user.hashed_password):
            raise InvalidCredentialsException()

        if not user.is_active:
            raise InvalidCredentialsException()

        token_payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
        }
        access_token = create_access_token(token_payload)
        refresh_token = create_refresh_token(token_payload)

        # Store refresh token in Redis
        await self.cache.set_refresh_token(
            user.id, refresh_token, settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        logger.info("User logged in", user_id=user.id, email=user.email)
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def refresh_access_token(self, refresh_token: str) -> str:
        """Validate refresh token and issue new access token."""
        token_data = verify_refresh_token(refresh_token)
        if token_data is None:
            raise TokenExpiredException()

        # Check if token is in Redis (not blacklisted)
        is_valid = await self.cache.is_refresh_token_valid(token_data.user_id, refresh_token)
        if not is_valid:
            raise TokenExpiredException()

        # Get user
        result = await self.db.execute(select(User).where(User.id == token_data.user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise TokenExpiredException()

        # Issue new access token
        new_access_token = create_access_token({
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
        })
        logger.info("Access token refreshed", user_id=user.id)
        return new_access_token

    async def logout(self, user_id: int, refresh_token: str, access_token: Optional[str] = None) -> None:
        """Blacklist refresh token and optionally the access token."""
        await self.cache.invalidate_refresh_token(user_id, refresh_token)
        
        if access_token:
            from app.core.security import decode_token_payload
            from datetime import datetime, timezone
            
            payload = decode_token_payload(access_token)
            if payload and "exp" in payload:
                exp = payload["exp"]
                now = int(datetime.now(timezone.utc).timestamp())
                ttl = exp - now
                if ttl > 0:
                    await self.cache.blacklist_access_token(access_token, ttl)
                    
        logger.info("User logged out", user_id=user_id)
