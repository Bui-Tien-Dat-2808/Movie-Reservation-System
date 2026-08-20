from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.queue_service import QueueService


@pytest.mark.asyncio
async def test_join_queue_direct_admission_when_below_threshold():
    """If active user count < max_active and queue is empty, issue pass_token immediately."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.zremrangebyscore = AsyncMock()
    mock_redis.zcard.side_effect = [5, 0]  # active_count = 5, waiting_count = 0
    mock_redis.zadd = AsyncMock()
    mock_redis.setex = AsyncMock()

    service = QueueService(mock_redis)
    res = await service.join_queue(showtime_id=1, user_id=100)

    assert res["in_queue"] is False
    assert res["pass_token"] is not None
    assert "vq_pass_1_100_" in res["pass_token"]
    assert res["rank"] == 0


@pytest.mark.asyncio
async def test_join_queue_places_user_in_redis_sorted_set():
    """If active count >= max_active, place user into waiting sorted set."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.zremrangebyscore = AsyncMock()
    mock_redis.zcard.side_effect = [30, 0, 1]  # active_count = 30, initial waiting = 0, new waiting = 1
    mock_redis.zadd = AsyncMock()
    mock_redis.zrank.return_value = 0

    service = QueueService(mock_redis)
    res = await service.join_queue(showtime_id=1, user_id=101)

    assert res["in_queue"] is True
    assert res["pass_token"] is None
    assert res["rank"] == 1
    assert res["estimated_wait_seconds"] == 10


@pytest.mark.asyncio
async def test_get_queue_status_promotes_top_user_when_slot_frees_up():
    """When a slot opens, top waiting user gets promoted and receives pass_token."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.zrank.return_value = 0
    mock_redis.zremrangebyscore = AsyncMock()
    mock_redis.zcard.return_value = 25  # Below max_active
    mock_redis.zrange.return_value = ["102"]  # User 102 is at top of queue
    mock_redis.zrem = AsyncMock()

    service = QueueService(mock_redis)
    res = await service.get_queue_status(showtime_id=1, user_id=102)

    assert res["in_queue"] is False
    assert res["pass_token"] is not None
    assert "vq_pass_1_102_" in res["pass_token"]


@pytest.mark.asyncio
async def test_validate_pass_token_checks_redis_key():
    """Validate pass_token against stored token in Redis."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "token_abc123"
    mock_redis.zremrangebyscore = AsyncMock()
    mock_redis.zcard.return_value = 100  # Queue active count = 100 (congested)

    service = QueueService(mock_redis)
    assert await service.validate_pass_token(showtime_id=1, user_id=100, token="token_abc123") is True
    assert await service.validate_pass_token(showtime_id=1, user_id=100, token="invalid_token") is False
