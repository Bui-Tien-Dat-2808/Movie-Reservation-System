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
        return count

    async def mock_keys(pattern: str):
        import fnmatch
        return [k for k in redis_store.keys() if fnmatch.fnmatch(k, pattern)]

    mock_redis.get.side_effect = mock_get
    mock_redis.setex.side_effect = mock_setex
    mock_redis.delete.side_effect = mock_delete
    mock_redis.keys.side_effect = mock_keys

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
