"""Unit tests for reservation business logic."""
import pytest
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


class TestCacheService:
    """Tests for CacheService."""

    @pytest.mark.asyncio
    async def test_get_returns_none_on_miss(self):
        from app.services.cache_service import CacheService
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        cache = CacheService(mock_redis)
        result = await cache.get("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        from app.services.cache_service import CacheService
        import json
        mock_redis = AsyncMock()
        stored_value = None

        async def fake_setex(key, ttl, value):
            nonlocal stored_value
            stored_value = value

        async def fake_get(key):
            return stored_value

        mock_redis.setex = fake_setex
        mock_redis.get = fake_get

        cache = CacheService(mock_redis)
        data = {"movie_id": 1, "title": "Test Movie"}
        await cache.set("movies:1", data, ttl=300)
        result = await cache.get("movies:1")
        assert result["title"] == "Test Movie"

    @pytest.mark.asyncio
    async def test_invalidate_token(self):
        from app.services.cache_service import CacheService
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)

        cache = CacheService(mock_redis)
        await cache.invalidate_refresh_token(1, "some.token.here_trailing")
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_refresh_token(self):
        from app.services.cache_service import CacheService
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock(return_value=True)

        cache = CacheService(mock_redis)
        await cache.set_refresh_token(1, "a.b.c_token_suffix", 7)
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_refresh_token_valid_true(self):
        from app.services.cache_service import CacheService
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="token_value")

        cache = CacheService(mock_redis)
        valid = await cache.is_refresh_token_valid(1, "some.token.suffix")
        assert valid is True

    @pytest.mark.asyncio
    async def test_is_refresh_token_valid_false(self):
        from app.services.cache_service import CacheService
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        cache = CacheService(mock_redis)
        valid = await cache.is_refresh_token_valid(1, "some.token.suffix")
        assert valid is False


class TestPagination:
    """Tests for pagination utilities."""

    def test_build_pagination_meta(self):
        from app.utils.pagination import build_pagination_meta
        meta = build_pagination_meta(total=100, page=2, page_size=20)
        assert meta.total == 100
        assert meta.total_pages == 5
        assert meta.has_next is True
        assert meta.has_prev is True
        assert meta.page == 2

    def test_pagination_last_page(self):
        from app.utils.pagination import build_pagination_meta
        meta = build_pagination_meta(total=50, page=5, page_size=10)
        assert meta.has_next is False
        assert meta.has_prev is True

    def test_pagination_first_page(self):
        from app.utils.pagination import build_pagination_meta
        meta = build_pagination_meta(total=50, page=1, page_size=10)
        assert meta.has_prev is False
        assert meta.has_next is True

    def test_pagination_empty(self):
        from app.utils.pagination import build_pagination_meta
        meta = build_pagination_meta(total=0, page=1, page_size=20)
        assert meta.total == 0
        assert meta.total_pages == 1
        assert meta.has_next is False
        assert meta.has_prev is False

    def test_paginate_function(self):
        from app.utils.pagination import paginate
        items = [{"id": i} for i in range(10)]
        result = paginate(items, 100, 1, 10)
        assert len(result.items) == 10
        assert result.meta.total == 100
