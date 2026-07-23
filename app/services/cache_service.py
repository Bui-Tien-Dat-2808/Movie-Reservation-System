import json
from typing import Optional

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class CacheService:
    """Redis cache service with JSON serialization and safety guards."""

    def __init__(self, redis_client: Optional[aioredis.Redis]):
        self.redis = redis_client

    async def get(self, key: str) -> Optional[dict | list]:
        """Get cached value by key."""
        if not self.redis:
            return None
        try:
            value = await self.redis.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.warning("Cache get failed", key=key, error=str(e))
        return None

    async def set(self, key: str, value: dict | list, ttl: int = 300) -> bool:
        """Set cached value with TTL (seconds)."""
        if not self.redis:
            return False
        try:
            await self.redis.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception as e:
            logger.warning("Cache set failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        """Delete cached value."""
        if not self.redis:
            return False
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.warning("Cache delete failed", key=key, error=str(e))
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern."""
        if not self.redis:
            return 0
        try:
            keys = await self.redis.keys(pattern)
            if keys:
                await self.redis.delete(*keys)
                return len(keys)
            return 0
        except Exception as e:
            logger.warning("Cache delete_pattern failed", pattern=pattern, error=str(e))
            return 0

    async def set_refresh_token(self, user_id: int, token: str, ttl_days: int) -> None:
        """Store refresh token in Redis."""
        if not self.redis:
            return
        key = f"refresh_token:{user_id}:{token[-20:]}"
        await self.redis.setex(key, ttl_days * 86400, token)

    async def is_refresh_token_valid(self, user_id: int, token: str) -> bool:
        """Check if refresh token exists and is not blacklisted."""
        if not self.redis:
            return False
        key = f"refresh_token:{user_id}:{token[-20:]}"
        value = await self.redis.get(key)
        return value is not None

    async def invalidate_refresh_token(self, user_id: int, token: str) -> None:
        """Blacklist (delete) a refresh token."""
        if not self.redis:
            return
        key = f"refresh_token:{user_id}:{token[-20:]}"
        await self.redis.delete(key)

    async def invalidate_all_user_tokens(self, user_id: int) -> None:
        """Invalidate all refresh tokens for a user."""
        if not self.redis:
            return
        pattern = f"refresh_token:{user_id}:*"
        await self.delete_pattern(pattern)

    async def blacklist_access_token(self, token: str, ttl: int) -> None:
        """Store blacklisted access token in Redis."""
        if not self.redis:
            return
        key = f"blacklist_access_token:{token[-20:]}"
        await self.redis.setex(key, ttl, "blacklisted")

    async def is_access_token_blacklisted(self, token: str) -> bool:
        """Check if access token is blacklisted."""
        if not self.redis:
            return False
        key = f"blacklist_access_token:{token[-20:]}"
        value = await self.redis.get(key)
        return value is not None
