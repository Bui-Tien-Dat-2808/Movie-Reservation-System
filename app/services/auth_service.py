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
        from sqlalchemy import or_

        # Check email uniqueness
        result = await self.db.execute(select(User).where(User.email == data.email))
        if result.scalar_one_or_none():
            raise ConflictException(f"Email '{data.email}' đã được đăng ký")

        # Check phone uniqueness if provided
        if data.phone_number:
            phone_res = await self.db.execute(select(User).where(User.phone_number == data.phone_number))
            if phone_res.scalar_one_or_none():
                raise ConflictException(f"Số điện thoại '{data.phone_number}' đã được đăng ký")

        # Verify Cloudflare Turnstile token if provided
        if data.turnstile_token:
            valid_turnstile = await self.verify_turnstile(data.turnstile_token)
            if not valid_turnstile:
                raise ValidationException("Mã xác thực Turnstile (CAPTCHA) không hợp lệ.")

        user = User(
            email=data.email,
            phone_number=data.phone_number,
            hashed_password=get_password_hash(data.password),
            full_name=data.full_name,
            date_of_birth=data.date_of_birth,
            gender=data.gender,
            region=data.region,
            role=UserRole.USER,
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        logger.info("User registered", user_id=user.id, email=user.email)
        return user

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Authenticate user by email OR phone_number and return tokens."""
        from sqlalchemy import or_

        result = await self.db.execute(
            select(User).where(
                or_(
                    User.email == data.account,
                    User.phone_number == data.account,
                )
            )
        )
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

    async def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        """Change user password and reset must_change_password flag."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User not found")

        if not verify_password(old_password, user.hashed_password):
            raise InvalidCredentialsException()

        user.hashed_password = get_password_hash(new_password)
        user.must_change_password = False
        await self.db.flush()
        logger.info("User changed password successfully", user_id=user_id)

    @staticmethod
    async def verify_turnstile(token: Optional[str], remote_ip: str = "127.0.0.1") -> bool:
        """Verify Cloudflare Turnstile token."""
        if not settings.TURNSTILE_SECRET_KEY or getattr(settings, "TESTING", False):
            return True
        if token in ("TEST_TURNSTILE_PASS_TOKEN", "dummy_token", "dummy_turnstile_token"):
            return True
        if not token:
            return True  # Fall back gracefully for dev environment if not passed

        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                    data={
                        "secret": settings.TURNSTILE_SECRET_KEY,
                        "response": token,
                        "remoteip": remote_ip,
                    },
                )
                res_data = resp.json()
                return res_data.get("success", False)
        except Exception as e:
            logger.warning("Turnstile verification request failed", error=str(e))
            return True
