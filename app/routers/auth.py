"""
Authentication API Router.

Provides endpoints for:
- User registration (create account)
- User login (email + password)
- User logout (revoke session)
- Token refresh
- Get current user info
- Get user's organizations list

All endpoints respect FEATURE_FLAG_AUTH setting.
When disabled, registration returns 503 Service Unavailable.
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..config import settings, AUTH_ENABLED
from ..auth.service import AuthService
from ..auth.organizations import OrganizationsService, UserAlreadyExistsError
from ..auth.dependencies import get_token_from_header, require_auth, get_optional_user
from ..auth.models import User


# ============================================================
# Request/Response Models
# ============================================================

class RegisterRequest(BaseModel):
    """Request model for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)

    @validator('full_name')
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()


class LoginRequest(BaseModel):
    """Request model for user login."""
    email: EmailStr
    password: str
    organization_id: Optional[str] = None


class UsernameLoginRequest(BaseModel):
    """Request model for username-based login (organization members)."""
    username: str
    password: str
    organization_id: str


class RefreshRequest(BaseModel):
    """Request model for token refresh."""
    refresh_token: str


class UpdateProfileRequest(BaseModel):
    """Request model for updating user profile."""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    current_password: Optional[str] = Field(None, min_length=1)
    new_password: Optional[str] = Field(None, min_length=8, max_length=128)


class TokenResponse(BaseModel):
    """Response model for authentication tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserResponse(BaseModel):
    """Response model for user info."""
    id: str
    email: Optional[str] = None
    username: Optional[str] = None
    full_name: str
    is_active: bool
    last_login_at: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class OrganizationListItem(BaseModel):
    """Organization in user's list."""
    id: str
    name: str
    slug: str
    role: str

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """Response model for successful login."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
    organization: Optional[OrganizationListItem] = None


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    detail: str


# ============================================================
# Router
# ============================================================

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


# ============================================================
# Helper Functions
# ============================================================

async def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """Get auth service instance."""
    return AuthService(db)


async def get_org_service(db: AsyncSession = Depends(get_db)) -> OrganizationsService:
    """Get organizations service instance."""
    return OrganizationsService(db)


def check_auth_enabled() -> None:
    """
    Check if authentication is enabled.

    Raises HTTPException if auth is disabled.
    """
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is disabled. Set FEATURE_FLAG_AUTH=true to enable."
        )


# ============================================================
# Endpoints
# ============================================================

@router.post(
    "/register",
    response_model=LoginResponse,
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Register new user",
    description="Create a new user account. Returns auth tokens. Organization is optional."
)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user account.

    Creates a user with email/password. Organization is NOT created automatically -
    user can create organizations later if needed. Returns authentication tokens.

    This endpoint only works when FEATURE_FLAG_AUTH=true.
    """
    check_auth_enabled()

    auth_service = AuthService(db)

    try:
        # Create user (without organization)
        user = await auth_service.create_user(
            email=data.email,
            password=data.password,
            full_name=data.full_name
        )

        # Create session without organization
        session = await auth_service.create_session(user.id, None)

        return _build_login_response(session, user, None)

    except ValueError as e:
        if "already exists" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "user_exists", "detail": str(e)}
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "detail": str(e)}
        )


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Login user",
    description="Authenticate with email and password. Returns auth tokens."
)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Login with email and password.

    Optionally select an organization after login by providing organization_id.
    If no organization is selected, user will need to select one via /auth/organizations.
    """
    check_auth_enabled()

    auth_service = AuthService(db)

    try:
        org_id = UUID(data.organization_id) if data.organization_id else None

        session, user = await auth_service.login(
            email=data.email,
            password=data.password,
            organization_id=org_id
        )

        # Get selected organization if any
        organization = None
        if session.organization_id:
            org_service = OrganizationsService(db)
            organization = await org_service.get_organization_by_id(
                session.organization_id
            )

        return _build_login_response(session, user, organization)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "detail": str(e)}
        )


@router.post(
    "/login-with-username",
    response_model=LoginResponse,
    responses={
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Login with username",
    description="Authenticate with username and password. For organization members."
)
async def login_with_username(
    data: UsernameLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Login with username and password.

    Requires organization_id - used by organization members.
    Automatically selects the organization context.
    """
    check_auth_enabled()

    auth_service = AuthService(db)

    try:
        org_id = UUID(data.organization_id)

        session, user = await auth_service.login_with_username(
            username=data.username,
            password=data.password,
            organization_id=org_id
        )

        # Get organization details and user's membership role
        org_service = OrganizationsService(db)
        organization = await org_service.get_organization_by_id(org_id)

        # Get actual membership role
        user_role = "member"
        try:
            user_orgs = await auth_service.get_user_organizations(user.id)
            for org in user_orgs:
                if str(org.id) == str(org_id):
                    user_role = getattr(org, 'membership_role', 'member')
                    break
        except Exception:
            pass

        return _build_login_response(session, user, organization, role=user_role)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "detail": str(e)}
        )


@router.post(
    "/logout",
    responses={
        200: {"description": "Successfully logged out"},
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Logout user",
    description="Revoke the current session token."
)
async def logout(
    token: Optional[str] = Depends(get_token_from_header),
    db: AsyncSession = Depends(get_db)
):
    """
    Logout the current user by revoking their session.

    Requires valid access token.
    """
    check_auth_enabled()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_token", "detail": "No token provided"}
        )

    auth_service = AuthService(db)

    try:
        # Get JTI from token
        payload = auth_service.decode_token(token)
        jti = payload.get("jti")

        if not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_token", "detail": "Token missing JTI"}
            )

        # Revoke session
        await auth_service.logout(jti)

        return {"message": "Successfully logged out"}

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "detail": str(e)}
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Refresh access token",
    description="Get new access token using refresh token."
)
async def refresh(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token using refresh token.

    Returns new access and refresh tokens.
    """
    check_auth_enabled()

    auth_service = AuthService(db)

    try:
        # Decode refresh token to get JTI
        payload = auth_service.decode_token(data.refresh_token)

        if not auth_service.verify_token_type(payload, "refresh"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_token_type", "detail": "Expected refresh token"}
            )

        refresh_jti = payload.get("jti")
        result = await auth_service.refresh_tokens(refresh_jti)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_refresh_token", "detail": "Refresh token invalid or expired"}
            )

        session, user = result

        return TokenResponse(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            token_type="bearer",
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "detail": str(e)}
        )


@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        200: {"description": "User info"},
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Get current user",
    description="Get information about the currently authenticated user."
)
async def get_me(
    user: User = Depends(require_auth)
):
    """
    Get current user information.

    Requires valid access token.
    """
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat() if user.created_at else None
    )


@router.get(
    "/organizations",
    response_model=list[OrganizationListItem],
    responses={
        200: {"description": "List of user's organizations"},
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Get user's organizations",
    description="Get list of all organizations the user belongs to."
)
async def get_organizations(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all organizations the authenticated user belongs to.

    Returns list with user's role in each organization.
    """
    auth_service = AuthService(db)
    organizations = await auth_service.get_user_organizations(user.id)

    return [
        OrganizationListItem(
            id=str(org.id),
            name=org.name,
            slug=org.slug,
            role=org.membership_role
        )
        for org in organizations
    ]


@router.post(
    "/select-organization/{organization_id}",
    response_model=TokenResponse,
    responses={
        200: {"description": "Organization selected"},
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Select organization context",
    description="Switch to a different organization. Returns new access token."
)
async def select_organization(
    organization_id: str,
    token: Optional[str] = Depends(get_token_from_header),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """
    Switch to a different organization context.

    Creates a new session with the selected organization.
    Returns new access and refresh tokens.
    """
    check_auth_enabled()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_token", "detail": "No token provided"}
        )

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    auth_service = AuthService(db)

    try:
        # Get current JTI
        payload = auth_service.decode_token(token)
        current_jti = payload.get("jti")

        # Switch organization
        new_session = await auth_service.switch_organization(
            user_id=user.id,
            organization_id=org_uuid,
            current_jti=current_jti
        )

        if not new_session:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "not_a_member", "detail": "Not a member of this organization"}
            )

        return TokenResponse(
            access_token=new_session.access_token,
            refresh_token=new_session.refresh_token,
            token_type="bearer",
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "detail": str(e)}
        )


@router.patch("/profile", response_model=UserResponse, summary="Update user profile")
async def update_profile(
    payload: UpdateProfileRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update display name and/or password for the current user."""
    check_auth_enabled()

    if payload.full_name:
        user.full_name = payload.full_name.strip()

    if payload.new_password:
        if not payload.current_password:
            raise HTTPException(status_code=400, detail="Укажите текущий пароль")
        if not user.verify_password(payload.current_password):
            raise HTTPException(status_code=400, detail="Неверный текущий пароль")
        user.set_password(payload.new_password)

    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=getattr(user, "username", None),
        full_name=user.full_name,
        is_active=user.is_active,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


# ============================================================
# Utility Functions
# ============================================================

def _build_login_response(
    session,
    user: User,
    organization,
    role: str = "owner"
) -> LoginResponse:
    """Build login response from session and user."""
    user_response = UserResponse(
        id=str(user.id),
        email=user.email,
        username=getattr(user, 'username', None),
        full_name=user.full_name,
        is_active=user.is_active,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat() if user.created_at else None
    )

    org_response = None
    if organization:
        org_response = OrganizationListItem(
            id=str(organization.id),
            name=organization.name,
            slug=organization.slug,
            role=role
        )

    return LoginResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_response,
        organization=org_response
    )
