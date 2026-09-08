"""
Pytest configuration and shared fixtures for Movie Reservation System tests.
"""
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.main import app
from app.models.user import User, UserRole

# Use SQLite in-memory for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create test database tables and provide a session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session
        await session.rollback()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide test HTTP client with overridden DB dependency."""
    from app.dependencies import get_db, get_redis
    from unittest.mock import AsyncMock, MagicMock

    # Dynamic Mock Redis using a dictionary
    redis_store = {}

    mock_redis = AsyncMock()

    zset_store = {}

    async def mock_get(key: str):
        return redis_store.get(key)

    async def mock_setex(key: str, ttl: int, value: str):
        redis_store[key] = value
        return True

    async def mock_delete(*keys: str):
        count = 0
        for k in keys:
            if k in redis_store:
                del redis_store[k]
                count += 1
            if k in zset_store:
                del zset_store[k]
                count += 1
        return count

    async def mock_keys(pattern: str):
        import fnmatch
        return [k for k in redis_store.keys() if fnmatch.fnmatch(k, pattern)]

    async def mock_zcard(key: str):
        return len(zset_store.get(key, {}))

    async def mock_zadd(key: str, mapping: dict):
        if key not in zset_store:
            zset_store[key] = {}
        for m, s in mapping.items():
            zset_store[key][m] = s
        return len(mapping)

    async def mock_zscore(key: str, member: str):
        return zset_store.get(key, {}).get(member)

    async def mock_zremrangebyscore(key: str, min_s: float, max_s: float):
        if key not in zset_store:
            return 0
        rem = [m for m, s in zset_store[key].items() if min_s <= s <= max_s]
        for m in rem:
            del zset_store[key][m]
        return len(rem)

    async def mock_zrank(key: str, member: str):
        if key not in zset_store or member not in zset_store[key]:
            return None
        sorted_members = sorted(zset_store[key].items(), key=lambda x: x[1])
        for idx, (m, _) in enumerate(sorted_members):
            if m == member:
                return idx
        return None

    async def mock_incr(key: str):
        val = int(redis_store.get(key, 0)) + 1
        redis_store[key] = str(val)
        return val

    async def mock_expire(key: str, seconds: int):
        return True

    async def mock_scan_iter(match: str = "*", count: int = 100):
        import fnmatch
        for k in list(redis_store.keys()) + list(zset_store.keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    mock_redis.get.side_effect = mock_get
    mock_redis.setex.side_effect = mock_setex
    mock_redis.delete.side_effect = mock_delete
    mock_redis.keys.side_effect = mock_keys
    mock_redis.scan_iter = mock_scan_iter
    mock_redis.zcard.side_effect = mock_zcard
    mock_redis.zadd.side_effect = mock_zadd
    mock_redis.zscore.side_effect = mock_zscore
    mock_redis.zremrangebyscore.side_effect = mock_zremrangebyscore
    mock_redis.zrank.side_effect = mock_zrank
    mock_redis.incr.side_effect = mock_incr
    mock_redis.expire.side_effect = mock_expire

    async def override_get_db():
        yield db_session

    async def override_get_redis():
        return mock_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a regular test user."""
    user = User(
        email="testuser@example.com",
        hashed_password=get_password_hash("TestPass@123"),
        full_name="Test User",
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_admin(db_session: AsyncSession) -> User:
    """Create a test admin user."""
    admin = User(
        email="admin@example.com",
        hashed_password=get_password_hash("AdminPass@123"),
        full_name="Test Admin",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


def get_auth_headers(user: User) -> dict:
    """Generate auth headers for a user."""
    token = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
    })
    return {"Authorization": f"Bearer {token}"}
