import pytest
from app.services.captcha_service import CaptchaService

class MockRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)

@pytest.mark.asyncio
async def test_captcha_create_and_verify_success(monkeypatch):
    mock_redis = MockRedis()
    async def mock_get_redis():
        return mock_redis

    monkeypatch.setattr("app.services.captcha_service.get_redis", mock_get_redis)

    captcha_id, img_bytes = await CaptchaService.create_challenge()
    assert captcha_id is not None
    assert len(img_bytes) > 0

    key = f"captcha:{captcha_id}"
    stored_code = mock_redis.store.get(key)
    assert stored_code is not None

    # Verify with correct code
    is_valid = await CaptchaService.verify(captcha_id, stored_code.lower())
    assert is_valid is True

    # Key must be deleted (single-use)
    assert key not in mock_redis.store

@pytest.mark.asyncio
async def test_captcha_single_use_deletion(monkeypatch):
    mock_redis = MockRedis()
    async def mock_get_redis():
        return mock_redis

    monkeypatch.setattr("app.services.captcha_service.get_redis", mock_get_redis)

    captcha_id, _ = await CaptchaService.create_challenge()
    key = f"captcha:{captcha_id}"
    stored_code = mock_redis.store.get(key)

    # First attempt wrong code
    is_valid_first = await CaptchaService.verify(captcha_id, "WRONG")
    assert is_valid_first is False

    # Second attempt with correct code should fail because key was deleted on first attempt
    is_valid_second = await CaptchaService.verify(captcha_id, stored_code)
    assert is_valid_second is False
