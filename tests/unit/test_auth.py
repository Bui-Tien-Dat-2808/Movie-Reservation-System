"""Unit tests for security utilities (JWT, password hashing)."""
import pytest
from datetime import timedelta

from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_access_token,
    verify_password,
    verify_refresh_token,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        """Password hash should verify correctly."""
        plain = "MyPassword@123"
        hashed = get_password_hash(plain)
        assert hashed != plain
        assert verify_password(plain, hashed)

    def test_wrong_password_fails(self):
        """Wrong password should not verify."""
        hashed = get_password_hash("CorrectPass@123")
        assert not verify_password("WrongPass@123", hashed)

    def test_hash_is_not_reversible(self):
        """Same password should produce different hashes each time."""
        h1 = get_password_hash("SamePass@123")
        h2 = get_password_hash("SamePass@123")
        assert h1 != h2  # bcrypt uses random salt


class TestAccessToken:
    def test_create_and_verify(self):
        """Access token should be created and verified."""
        payload = {"sub": "1", "email": "user@test.com", "role": "user"}
        token = create_access_token(payload)
        assert token is not None

        data = verify_access_token(token)
        assert data is not None
        assert data.user_id == 1
        assert data.email == "user@test.com"
        assert data.role == "user"

    def test_invalid_token_returns_none(self):
        """Invalid token should return None."""
        data = verify_access_token("invalid.token.here")
        assert data is None

    def test_expired_token_returns_none(self):
        """Expired token should return None."""
        payload = {"sub": "1", "email": "user@test.com", "role": "user"}
        token = create_access_token(payload, expires_delta=timedelta(seconds=-1))
        data = verify_access_token(token)
        assert data is None

    def test_refresh_token_rejected_as_access(self):
        """Refresh token should not validate as access token."""
        payload = {"sub": "1", "email": "user@test.com", "role": "user"}
        refresh = create_refresh_token(payload)
        data = verify_access_token(refresh)
        assert data is None


class TestRefreshToken:
    def test_create_and_verify(self):
        """Refresh token should be created and verified."""
        payload = {"sub": "42", "email": "admin@test.com", "role": "admin"}
        token = create_refresh_token(payload)
        data = verify_refresh_token(token)
        assert data is not None
        assert data.user_id == 42
        assert data.role == "admin"

    def test_access_token_rejected_as_refresh(self):
        """Access token should not validate as refresh token."""
        payload = {"sub": "1", "email": "user@test.com", "role": "user"}
        access = create_access_token(payload)
        data = verify_refresh_token(access)
        assert data is None
