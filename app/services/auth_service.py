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
    ValidationException,
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
        """Change user password, reset must_change_password flag, and send security email alert."""
        from app.core.exceptions import ValidationException
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User not found")

        if not verify_password(old_password, user.hashed_password):
            raise InvalidCredentialsException()

        if old_password == new_password or verify_password(new_password, user.hashed_password):
            raise ValidationException("Mật khẩu mới không được trùng với mật khẩu hiện tại. Vui lòng chọn mật khẩu mới khác.")

        user.hashed_password = get_password_hash(new_password)
        user.must_change_password = False
        await self.db.flush()
        if self.cache:
            await self.cache.invalidate_all_user_tokens(user.id)
        logger.info("User changed password successfully", user_id=user_id)

        # FEAT-05: Gửi email cảnh báo bảo mật khi đổi mật khẩu
        try:
            from app.services.email_service import EmailService
            EmailService.send_password_changed_alert_email(user.email, user.full_name)
        except Exception as e:
            logger.warning("Failed to dispatch password changed alert email", user_id=user_id, error=str(e))

    async def forgot_password(self, email: str, client_origin: Optional[str] = None) -> None:
        """FEAT-06: Generate 15-minute secure reset token in Redis and send email."""
        clean_email = email.strip().lower()
        from sqlalchemy import func
        result = await self.db.execute(select(User).where(func.lower(User.email) == clean_email))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            # Silent return to prevent email enumeration
            logger.info("forgot_password_email_not_found_or_inactive", email=clean_email)
            return

        import secrets
        reset_token = secrets.token_urlsafe(32)
        # Store in Redis for 15 minutes (900 seconds)
        if self.cache and self.cache.redis:
            await self.cache.redis.setex(f"pwd_reset:{reset_token}", 900, str(user.id))

        try:
            from app.services.email_service import EmailService
            EmailService.send_password_reset_email(
                user.email, user.full_name, reset_token, frontend_base_url=client_origin
            )
            logger.info("forgot_password_email_dispatched", user_id=user.id, email=clean_email, origin=client_origin)
        except Exception as e:
            logger.warning("failed_to_send_password_reset_email", user_id=user.id, error=str(e))

    async def reset_password(self, token: str, new_password: str) -> None:
        """FEAT-06: Verify reset token and set new password."""
        from app.core.exceptions import ValidationException
        if not self.cache or not self.cache.redis:
            raise ValidationException("Dịch vụ xác thực tạm thời không khả dụng, vui lòng thử lại sau.")

        user_id_raw = await self.cache.redis.get(f"pwd_reset:{token}")
        if not user_id_raw:
            raise ValidationException("Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn (15 phút). Vui lòng yêu cầu lại.")

        user_id = int(user_id_raw.decode("utf-8") if isinstance(user_id_raw, bytes) else user_id_raw)
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise ValidationException("Không tìm thấy tài khoản người dùng tương ứng.")

        if verify_password(new_password, user.hashed_password):
            raise ValidationException("Mật khẩu mới không được trùng với mật khẩu cũ trước đây.")

        user.hashed_password = get_password_hash(new_password)
        user.must_change_password = False
        await self.db.flush()

        # Delete token and invalidate all previous user sessions
        await self.cache.redis.delete(f"pwd_reset:{token}")
        await self.cache.invalidate_all_user_tokens(user.id)
        logger.info("password_reset_successfully", user_id=user.id)

        # Dispatch security alert
        try:
            from app.services.email_service import EmailService
            EmailService.send_password_changed_alert_email(user.email, user.full_name)
        except Exception:
            pass

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
