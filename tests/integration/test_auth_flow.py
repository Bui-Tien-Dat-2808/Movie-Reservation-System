"""Integration tests for Authentication API."""
import pytest
import pytest_asyncio
from httpx import AsyncClient


class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        """Should successfully register a new user."""
        response = await client.post("/api/v1/auth/register", json={
            "email": "newuser@test.com",
            "full_name": "New User",
            "password": "ValidPass@1",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@test.com"
        assert data["role"] == "user"
        assert "hashed_password" not in data

    async def test_register_duplicate_email(self, client: AsyncClient):
        """Should reject duplicate email registration."""
        payload = {
            "email": "dup@test.com",
            "full_name": "Dup User",
            "password": "ValidPass@1",
        }
        await client.post("/api/v1/auth/register", json=payload)
        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 409

    async def test_register_invalid_email(self, client: AsyncClient):
        """Should reject invalid email format."""
        response = await client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "full_name": "User",
            "password": "ValidPass@1",
        })
        assert response.status_code == 422

    async def test_register_weak_password(self, client: AsyncClient):
        """Should reject weak password."""
        response = await client.post("/api/v1/auth/register", json={
            "email": "user@test.com",
            "full_name": "User",
            "password": "weakpassword",
        })
        assert response.status_code == 422


class TestLogin:
    async def test_login_success(self, client: AsyncClient, test_user):
        """Should successfully login and return tokens."""
        response = await client.post("/api/v1/auth/login", json={
            "email": "testuser@example.com",
            "password": "TestPass@123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient, test_user):
        """Should reject wrong password."""
        response = await client.post("/api/v1/auth/login", json={
            "email": "testuser@example.com",
            "password": "WrongPass@999",
        })
        assert response.status_code == 401

    async def test_login_nonexistent_email(self, client: AsyncClient):
        """Should reject non-existent email."""
        response = await client.post("/api/v1/auth/login", json={
            "email": "ghost@test.com",
            "password": "ValidPass@1",
        })
        assert response.status_code == 401


class TestGetMe:
    async def test_get_me_authenticated(self, client: AsyncClient, test_user):
        """Should return current user profile."""
        from tests.conftest import get_auth_headers
        headers = get_auth_headers(test_user)
        response = await client.get("/api/v1/users/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email

    async def test_get_me_unauthenticated(self, client: AsyncClient):
        """Should reject unauthenticated request."""
        response = await client.get("/api/v1/users/me")
        assert response.status_code == 401


class TestRefreshToken:
    async def test_invalid_refresh_token(self, client: AsyncClient):
        """Invalid refresh token should return 401."""
        response = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid.token.here",
        })
        assert response.status_code == 401


class TestLogoutFlow:
    async def test_logout_invalidates_access_token(self, client: AsyncClient, test_user):
        """Should blacklist the access token on logout, blocking profile view/update."""
        from tests.conftest import get_auth_headers
        headers = get_auth_headers(test_user)

        # 1. Login to get both access & refresh tokens
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "testuser@example.com",
            "password": "TestPass@123",
        })
        assert login_resp.status_code == 200
        tokens = login_resp.json()
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]

        user_headers = {"Authorization": f"Bearer {access_token}"}

        # 2. Get profile before logout (should work)
        me_resp = await client.get("/api/v1/users/me", headers=user_headers)
        assert me_resp.status_code == 200

        # 3. Logout (blacklists both refresh & access tokens)
        logout_resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
            headers=user_headers
        )
        assert logout_resp.status_code == 204

        # 4. Try to get profile again using the same access token (should fail with 401)
        after_me_resp = await client.get("/api/v1/users/me", headers=user_headers)
        assert after_me_resp.status_code == 401
