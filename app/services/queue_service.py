import json
import time
import uuid
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
import structlog

from app.config import settings

logger = structlog.get_logger()


class QueueService:
    """Service to handle high-concurrency Virtual Queue & Waiting Room using Redis."""

    def __init__(self, redis_client: Optional[aioredis.Redis]):
        self.redis = redis_client
        self.max_active = settings.QUEUE_MAX_ACTIVE_USERS_PER_SHOWTIME
        self.token_ttl = settings.QUEUE_PASS_TOKEN_EXPIRE_MINUTES * 60

    def _get_waiting_key(self, showtime_id: int) -> str:
        return f"queue:showtime:{showtime_id}:waiting"

    def _get_active_key(self, showtime_id: int) -> str:
        return f"queue:showtime:{showtime_id}:active"

    def _get_token_key(self, showtime_id: int, user_id: int) -> str:
        return f"queue:pass_token:{showtime_id}:{user_id}"

    async def join_queue(self, showtime_id: int, user_id: int) -> Dict[str, Any]:
        """User enters the virtual queue for a specific showtime."""
        if not self.redis or not settings.QUEUE_ENABLED:
            # Bypass queue if Redis is disabled
            dummy_token = f"bypass_{showtime_id}_{user_id}_{uuid.uuid4().hex[:8]}"
            return {
                "in_queue": False,
                "pass_token": dummy_token,
                "rank": 0,
                "total_waiting": 0,
                "estimated_wait_seconds": 0,
            }

        user_str = str(user_id)
        waiting_key = self._get_waiting_key(showtime_id)
        active_key = self._get_active_key(showtime_id)
        token_key = self._get_token_key(showtime_id, user_id)

        # 1. Check existing pass token
        existing_token = await self.redis.get(token_key)
        if existing_token:
            return {
                "in_queue": False,
                "pass_token": existing_token,
                "rank": 0,
                "total_waiting": 0,
                "estimated_wait_seconds": 0,
            }

        # 2. Purge expired active slots and check active slot count
        now = time.time()
        await self.redis.zremrangebyscore(active_key, 0, now)
        active_count = await self.redis.zcard(active_key)
        waiting_count = await self.redis.zcard(waiting_key)

        # 3. Direct admission if below active threshold and queue is empty
        if active_count < self.max_active and waiting_count == 0:
            pass_token = await self._issue_pass_token(showtime_id, user_id)
            return {
                "in_queue": False,
                "pass_token": pass_token,
                "rank": 0,
                "total_waiting": 0,
                "estimated_wait_seconds": 0,
            }

        # 4. Enqueue user into Redis Sorted Set (ZADD) with timestamp as score
        await self.redis.zadd(waiting_key, {user_str: now})
        rank = await self.redis.zrank(waiting_key, user_str)
        total_waiting = await self.redis.zcard(waiting_key)

        user_rank = (rank + 1) if rank is not None else 1
        est_seconds = user_rank * 10

        logger.info(
            "User joined queue",
            showtime_id=showtime_id,
            user_id=user_id,
            rank=user_rank,
            total_waiting=total_waiting,
        )

        return {
            "in_queue": True,
            "pass_token": None,
            "rank": user_rank,
            "total_waiting": total_waiting,
            "estimated_wait_seconds": est_seconds,
        }

    async def get_queue_status(self, showtime_id: int, user_id: int) -> Dict[str, Any]:
        """Check status of user in the queue and promote if slot opens up."""
        if not self.redis or not settings.QUEUE_ENABLED:
            dummy_token = f"bypass_{showtime_id}_{user_id}_{uuid.uuid4().hex[:8]}"
            return {
                "in_queue": False,
                "pass_token": dummy_token,
                "rank": 0,
                "total_waiting": 0,
                "estimated_wait_seconds": 0,
            }

        user_str = str(user_id)
        waiting_key = self._get_waiting_key(showtime_id)
        active_key = self._get_active_key(showtime_id)
        token_key = self._get_token_key(showtime_id, user_id)

        # 1. Check if user already holds a valid pass token
        existing_token = await self.redis.get(token_key)
        if existing_token:
            return {
                "in_queue": False,
                "pass_token": existing_token,
                "rank": 0,
                "total_waiting": 0,
                "estimated_wait_seconds": 0,
            }

        # 2. Check current rank in waiting queue
        rank = await self.redis.zrank(waiting_key, user_str)
        if rank is None:
            # User not in queue or was removed, join queue again
            return await self.join_queue(showtime_id, user_id)

        now = time.time()
        await self.redis.zremrangebyscore(active_key, 0, now)
        active_count = await self.redis.zcard(active_key)

        # 3. Promotion check: if active slot available and user is at top of queue
        if active_count < self.max_active:
            top_users = await self.redis.zrange(waiting_key, 0, 0)
            if top_users and top_users[0] == user_str:
                pass_token = await self._issue_pass_token(showtime_id, user_id)
                await self.redis.zrem(waiting_key, user_str)
                return {
                    "in_queue": False,
                    "pass_token": pass_token,
                    "rank": 0,
                    "total_waiting": 0,
                    "estimated_wait_seconds": 0,
                }

        total_waiting = await self.redis.zcard(waiting_key)
        user_rank = rank + 1
        est_seconds = user_rank * 10

        return {
            "in_queue": True,
            "pass_token": None,
            "rank": user_rank,
            "total_waiting": total_waiting,
            "estimated_wait_seconds": est_seconds,
        }

    async def leave_queue(self, showtime_id: int, user_id: int) -> bool:
        """Release user from queue or active session."""
        if not self.redis:
            return True

        user_str = str(user_id)
        waiting_key = self._get_waiting_key(showtime_id)
        active_key = self._get_active_key(showtime_id)
        token_key = self._get_token_key(showtime_id, user_id)

        await self.redis.zrem(waiting_key, user_str)
        await self.redis.zrem(active_key, user_str)
        await self.redis.delete(token_key)

        logger.info("User left queue / released slot", showtime_id=showtime_id, user_id=user_id)
        return True

    async def validate_pass_token(self, showtime_id: int, user_id: int, token: Optional[str]) -> bool:
        """Validate if user holds an active, non-expired Queue Pass Token."""
        if not settings.QUEUE_ENABLED or not self.redis:
            return True

        if token:
            if token.startswith("bypass_"):
                return True
            token_key = self._get_token_key(showtime_id, user_id)
            stored_token = await self.redis.get(token_key)
            if stored_token and stored_token == token:
                return True

        # Non-congested fallback: If waiting queue is empty and active count < max_active,
        # auto-issue pass token and admit user so normal seat booking is never blocked!
        active_key = self._get_active_key(showtime_id)
        waiting_key = self._get_waiting_key(showtime_id)

        now = time.time()
        await self.redis.zremrangebyscore(active_key, 0, now)
        active_count = await self.redis.zcard(active_key)
        waiting_count = await self.redis.zcard(waiting_key)

        if active_count < self.max_active and waiting_count == 0:
            await self._issue_pass_token(showtime_id, user_id)
            return True

        return False

    async def _issue_pass_token(self, showtime_id: int, user_id: int) -> str:
        """Issue pass token, add user to active set with expiration score, and set token with TTL."""
        token = f"vq_pass_{showtime_id}_{user_id}_{uuid.uuid4().hex}"
        user_str = str(user_id)

        active_key = self._get_active_key(showtime_id)
        token_key = self._get_token_key(showtime_id, user_id)

        exp_timestamp = time.time() + self.token_ttl
        await self.redis.zadd(active_key, {user_str: exp_timestamp})
        await self.redis.setex(token_key, self.token_ttl, token)

        logger.info(
            "Issued Queue Pass Token",
            showtime_id=showtime_id,
            user_id=user_id,
            ttl_seconds=self.token_ttl,
        )
        return token
