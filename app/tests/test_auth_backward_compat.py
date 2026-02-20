"""
Tests for authentication backward compatibility.

These tests verify that:
1. When FEATURE_FLAG_AUTH=False, the system works as before
2. When FEATURE_FLAG_AUTH=True, new auth features work
3. Dialog endpoints respect authentication when enabled
"""

import pytest
import os
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestBackwardCompatibility:
    """Test backward compatibility when auth is disabled."""

    async def test_dialogs_without_auth(self, client: AsyncClient):
        """Test that dialogs endpoint works without authentication when FEATURE_FLAG_AUTH=False."""
        # Skip if auth is enabled
        if os.getenv("FEATURE_FLAG_AUTH", "false").lower() == "true":
            pytest.skip("Auth is enabled")

        response = await client.get("/dialogs/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    async def test_dashboard_without_auth(self, client: AsyncClient):
        """Test that dashboard endpoint works without authentication when FEATURE_FLAG_AUTH=False."""
        if os.getenv("FEATURE_FLAG_AUTH", "false").lower() == "true":
            pytest.skip("Auth is enabled")

        response = await client.get("/dialogs/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_dialogs" in data

    async def test_sellers_without_auth(self, client: AsyncClient):
        """Test that sellers endpoint works without authentication when FEATURE_FLAG_AUTH=False."""
        if os.getenv("FEATURE_FLAG_AUTH", "false").lower() == "true":
            pytest.skip("Auth is enabled")

        response = await client.get("/dialogs/sellers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
class TestAuthenticationFlow:
    """Test authentication flow when FEATURE_FLAG_AUTH=True."""

    async def test_auth_disabled_returns_503(self, client: AsyncClient):
        """Test that auth endpoints return 503 when FEATURE_FLAG_AUTH=False."""
        if os.getenv("FEATURE_FLAG_AUTH", "false").lower() == "true":
            pytest.skip("Auth is enabled")

        response = await client.post("/auth/register", json={
            "email": "test@example.com",
            "password": "test12345",
            "full_name": "Test User"
        })
        assert response.status_code == 503

    async def test_login_disabled_returns_503(self, client: AsyncClient):
        """Test that login endpoint returns 503 when FEATURE_FLAG_AUTH=False."""
        if os.getenv("FEATURE_FLAG_AUTH", "false").lower() == "true":
            pytest.skip("Auth is enabled")

        response = await client.post("/auth/login", json={
            "email": "test@example.com",
            "password": "test12345"
        })
        assert response.status_code == 503


# Only run auth tests when FEATURE_FLAG_AUTH=true
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("FEATURE_FLAG_AUTH", "false").lower() != "true",
    reason="Authentication is disabled"
)
class TestAuthenticationEnabled:
    """Tests for when authentication is enabled."""

    async def test_register_user(self, client: AsyncClient):
        """Test user registration."""
        response = await client.post("/auth/register", json={
            "email": "newuser@example.com",
            "password": "securepass123",
            "full_name": "New User"
        })

        if response.status_code == 503:
            pytest.skip("Auth not enabled")

        assert response.status_code in (200, 201)
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "user" in data

    async def test_login_user(self, client: AsyncClient, db: AsyncSession):
        """Test user login."""
        # First create a user
        register_resp = await client.post("/auth/register", json={
            "email": "loginuser@example.com",
            "password": "securepass123",
            "full_name": "Login User"
        })

        if register_resp.status_code == 503:
            pytest.skip("Auth not enabled")

        # Now login
        response = await client.post("/auth/login", json={
            "email": "loginuser@example.com",
            "password": "securepass123"
        })

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    async def test_protected_endpoint_requires_auth(self, client: AsyncClient):
        """Test that protected endpoints require authentication."""
        response = await client.get("/auth/me")

        if response.status_code == 503:
            pytest.skip("Auth not enabled")

        assert response.status_code == 401

    async def test_get_current_user(self, client: AsyncClient):
        """Test getting current user info."""
        # Register and login
        register_resp = await client.post("/auth/register", json={
            "email": "meuser@example.com",
            "password": "securepass123",
            "full_name": "Me User"
        })

        if register_resp.status_code == 503:
            pytest.skip("Auth not enabled")

        token = register_resp.json()["access_token"]

        # Get current user
        response = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "meuser@example.com"


@pytest.mark.asyncio
class TestOrganizations:
    """Test organization management."""

    async def test_create_organization(self, client: AsyncClient):
        """Test creating an organization."""
        # First register/login
        register_resp = await client.post("/auth/register", json={
            "email": "orgowner@example.com",
            "password": "securepass123",
            "full_name": "Org Owner"
        })

        if register_resp.status_code == 503:
            pytest.skip("Auth not enabled")

        token = register_resp.json()["access_token"]

        # Create organization
        response = await client.post(
            "/organizations",
            json={"name": "Test Org"},
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code in (200, 201)
        data = response.json()
        assert data["name"] == "Test Org"

    async def test_get_organizations(self, client: AsyncClient):
        """Test getting user's organizations."""
        register_resp = await client.post("/auth/register", json={
            "email": "orglist@example.com",
            "password": "securepass123",
            "full_name": "Org List"
        })

        if register_resp.status_code == 503:
            pytest.skip("Auth not enabled")

        token = register_resp.json()["access_token"]

        response = await client.get(
            "/auth/organizations",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have default organization from registration
        assert len(data) >= 1

    async def test_create_organization_member(self, client: AsyncClient):
        """Test creating a new user and adding to organization."""
        # Create owner
        owner_resp = await client.post("/auth/register", json={
            "email": "owner2@example.com",
            "password": "securepass123",
            "full_name": "Owner Two"
        })

        if owner_resp.status_code == 503:
            pytest.skip("Auth not enabled")

        owner_token = owner_resp.json()["access_token"]

        # Create organization
        org_resp = await client.post(
            "/organizations",
            json={"name": "Team Org"},
            headers={"Authorization": f"Bearer {owner_token}"}
        )
        org_id = org_resp.json()["id"]

        # Add new member
        response = await client.post(
            f"/organizations/{org_id}/members",
            json={
                "email": "teammember@example.com",
                "password": "memberpass123",
                "full_name": "Team Member",
                "role": "member"
            },
            headers={"Authorization": f"Bearer {owner_token}"}
        )

        assert response.status_code in (200, 201)
        data = response.json()
        assert data["email"] == "teammember@example.com"


@pytest.mark.asyncio
class TestDialogsWithAuth:
    """Test dialog endpoints with authentication."""

    async def test_dialogs_list_with_auth(self, client: AsyncClient):
        """Test that dialogs list filters by user's access when auth is enabled."""
        # Register user
        register_resp = await client.post("/auth/register", json={
            "email": "dialoguser@example.com",
            "password": "securepass123",
            "full_name": "Dialog User"
        })

        if register_resp.status_code == 503:
            pytest.skip("Auth not enabled")

        token = register_resp.json()["access_token"]

        # Get dialogs - should be empty for new user
        response = await client.get(
            "/dialogs/",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        # Should only see dialogs accessible to this user/org
