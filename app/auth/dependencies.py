"""
Authentication dependencies for FastAPI routes.

Provides dependency functions for route authentication:
- get_optional_user: Get user if authenticated, None otherwise
- require_auth: Require user to be authenticated
- get_current_user: Get authenticated user with session
- get_current_organization: Get currently selected organization
- require_role: Require specific role in current organization

Usage:
    from fastapi import Depends
    from app.auth.dependencies import require_auth, get_current_organization

    @app.get("/protected")
    async def protected_route(user = Depends(require_auth)):
        return {"user": user.email}

    @app.get("/org-dialogs")
    async def org_dialogs(
        org = Depends(get_current_organization),
        user = Depends(require_auth)
    ):
        # Filter dialogs by organization
        pass
"""

from typing import Optional, Annotated
from uuid import UUID
from fastapi import Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from .service import AuthService
from .models import User, Organization, Membership, UserRole
from ..config import settings


# ============================================================
# Token Extraction
# ============================================================

async def get_token_from_header(
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Extract JWT token from Authorization header.

    Args:
        authorization: Value of Authorization header

    Returns:
        Token string or None if not present
    """
    if not authorization:
        return None

    if authorization.startswith("Bearer "):
        return authorization[7:]  # Remove "Bearer " prefix

    return None


async def get_token_from_cookie(
    cookie: Optional[str] = None
) -> Optional[str]:
    """
    Extract JWT token from cookie.

    Args:
        cookie: Cookie header value

    Returns:
        Token string or None if not present
    """
    # This would parse cookies for 'access_token'
    # For now, we'll use header-based auth
    return None


# ============================================================
# User Dependencies
# ============================================================

async def _get_user_from_token(
    token: Optional[str],
    db: AsyncSession
) -> Optional[tuple[User, Optional[UUID]]]:
    """
    Helper to extract user and organization from token.

    Args:
        token: JWT token string or None
        db: Database session

    Returns:
        Tuple of (User, organization_id) or None
    """
    if not token:
        return None

    try:
        auth_service = AuthService(db)
        payload = auth_service.decode_token(token)

        # Verify it's an access token
        if not auth_service.verify_token_type(payload, "access"):
            return None

        # Get user
        user_id = UUID(payload.get("sub"))
        user = await auth_service.get_user_by_id(user_id)

        if not user or not user.is_active:
            return None

        # Get organization from token if present
        organization_id = None
        if "org_id" in payload:
            organization_id = UUID(payload["org_id"])

        # Verify session is still active
        jti = payload.get("jti")
        session = await auth_service.get_session_by_jti(jti)
        if not session or not session.is_valid():
            return None

        return user, organization_id

    except (ValueError, KeyError):
        return None


async def get_optional_user(
    token: Optional[str] = Depends(get_token_from_header),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    Get user if authenticated, None otherwise.

    This is the base dependency that doesn't require authentication.
    Use this for routes that work both with and without auth.

    Args:
        token: JWT token from header
        db: Database session

    Returns:
        User object or None if not authenticated

    Example:
        @app.get("/api/data")
        async def get_data(user: Optional[User] = Depends(get_optional_user)):
            if user:
                return {"data": "personalized", "user": user.email}
            return {"data": "public"}
    """
    if not settings.auth_enabled:
        # Auth disabled - no user
        return None

    result = await _get_user_from_token(token, db)
    if result:
        return result[0]
    return None


async def require_auth(
    token: Optional[str] = Depends(get_token_from_header),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Require user to be authenticated.

    Raises HTTPException if user is not authenticated.

    Args:
        token: JWT token from header
        db: Database session

    Returns:
        Authenticated User object

    Raises:
        HTTPException: If authentication is required but not provided

    Example:
        @app.get("/api/protected")
        async def protected_route(user: User = Depends(require_auth)):
            return {"message": f"Hello {user.email}"}
    """
    if not settings.auth_enabled:
        # Auth disabled - this dependency shouldn't be used
        # but for backward compatibility, we'll raise an error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is disabled. Set FEATURE_FLAG_AUTH=true to enable."
        )

    result = await _get_user_from_token(token, db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user, _ = result
    return user


async def get_current_user(
    token: Optional[str] = Depends(get_token_from_header),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    Get current authenticated user with full session context.

    Similar to get_optional_user but returns None instead of raising
    when auth is enabled but no token provided.

    Args:
        token: JWT token from header
        db: Database session

    Returns:
        User object or None
    """
    if not settings.auth_enabled:
        return None

    result = await _get_user_from_token(token, db)
    if result:
        return result[0]
    return None


# ============================================================
# Organization Dependencies
# ============================================================

class OrganizationContext:
    """
    Container for organization context in requests.

    Holds the currently selected organization and user's membership role.
    """

    def __init__(
        self,
        organization: Organization,
        membership: Membership
    ):
        self.organization = organization
        self.membership = membership
        self.role = UserRole(membership.role)

    def can_manage_members(self) -> bool:
        """Check if user can manage organization members."""
        return self.role.can_manage_members()

    def can_manage_dialogs(self) -> bool:
        """Check if user can manage dialogs."""
        return self.role.can_manage_dialogs()

    def can_view_dialogs(self) -> bool:
        """Check if user can view dialogs."""
        return self.role.can_view_dialogs()

    def is_owner(self) -> bool:
        """Check if user is organization owner."""
        return self.role == UserRole.OWNER


async def get_current_organization(
    token: Optional[str] = Depends(get_token_from_header),
    db: AsyncSession = Depends(get_db)
) -> Optional[OrganizationContext]:
    """
    Get currently selected organization from token.

    Returns organization context with user's role if organization
    is selected in the current session.

    Args:
        token: JWT token from header
        db: Database session

    Returns:
        OrganizationContext object or None if no org selected

    Example:
        @app.get("/api/org/dialogs")
        async def org_dialogs(
            org_ctx: Optional[OrganizationContext] = Depends(get_current_organization)
        ):
            if org_ctx:
                return {"org": org_ctx.organization.name}
            return {"message": "No organization selected"}
    """
    if not settings.auth_enabled:
        return None

    result = await _get_user_from_token(token, db)
    if not result:
        return None

    user, organization_id = result

    if not organization_id:
        return None

    # Get organization and membership
    auth_service = AuthService(db)

    result = await db.execute(
        select(Organization, Membership).join(
            Membership,
            Membership.organization_id == Organization.id
        ).where(
            Membership.user_id == user.id,
            Membership.organization_id == organization_id,
            Membership.is_active == True
        )
    )

    row = result.first()
    if not row:
        return None

    organization, membership = row
    return OrganizationContext(organization, membership)


async def require_organization(
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization)
) -> OrganizationContext:
    """
    Require an organization to be selected.

    Raises HTTPException if no organization is selected.

    Args:
        org_ctx: Organization context from token

    Returns:
        OrganizationContext object

    Raises:
        HTTPException: If no organization is selected
    """
    if not org_ctx:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization selection required"
        )

    return org_ctx


# ============================================================
# Role-based Dependencies
# ============================================================

def require_role(required_role: UserRole):
    """
    Create dependency that requires specific role in organization.

    Args:
        required_role: Minimum required role

    Returns:
        Dependency function

    Example:
        @app.delete("/api/org/members/{member_id}")
        async def remove_member(
            org_ctx: OrganizationContext = Depends(require_role(UserRole.ADMIN))
        ):
            # Only admins and owners can access
            pass
    """
    async def check_role(
        org_ctx: Optional[OrganizationContext] = Depends(get_current_organization)
    ) -> OrganizationContext:
        if not org_ctx:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization selection required"
            )

        # Role hierarchy: OWNER > ADMIN > MEMBER > VIEWER
        role_hierarchy = {
            UserRole.OWNER: 4,
            UserRole.ADMIN: 3,
            UserRole.MEMBER: 2,
            UserRole.VIEWER: 1
        }

        if role_hierarchy.get(org_ctx.role, 0) < role_hierarchy.get(required_role, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required_role.value}' or higher required"
            )

        return org_ctx

    return check_role


# ============================================================
# Type Aliases for Common Use Cases
# ============================================================

# User authenticated (required)
AuthenticatedUser = Annotated[User, Depends(require_auth)]

# Optional user (may be None)
OptionalUser = Annotated[Optional[User], Depends(get_optional_user)]

# Current user with context
CurrentUser = Annotated[Optional[User], Depends(get_current_user)]

# Organization context (optional)
OptionalOrgContext = Annotated[Optional[OrganizationContext], Depends(get_current_organization)]

# Organization context (required)
RequiredOrgContext = Annotated[OrganizationContext, Depends(require_organization)]

# Admin or higher role
AdminOrOwner = Annotated[OrganizationContext, Depends(require_role(UserRole.ADMIN))]

# Owner only
OwnerOnly = Annotated[OrganizationContext, Depends(require_role(UserRole.OWNER))]
