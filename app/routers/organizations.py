"""
Organizations API Router.

Provides endpoints for:
- Create organization
- Get organization details
- Update organization
- Delete organization
- List organization members
- Add member (create new user directly)
- Remove member
- Change member role
- Get organization statistics

All endpoints require authentication and appropriate permissions.
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from pydantic import BaseModel, EmailStr, Field, validator
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..config import AUTH_ENABLED
from ..auth.dependencies import require_auth, require_role, OwnerOnly, AdminOrOwner, get_current_organization
from ..auth.models import User, Organization, Membership, UserRole
from ..auth.dependencies import OrganizationContext
from ..auth.organizations import (
    OrganizationsService,
    OrganizationAlreadyExistsError,
    UserAlreadyExistsError,
    MemberNotFoundError,
    InsufficientPermissionsError
)


# ============================================================
# Request/Response Models
# ============================================================

class CreateOrganizationRequest(BaseModel):
    """Request model for creating organization."""
    name: str = Field(..., min_length=1, max_length=255)
    slug: Optional[str] = Field(None, max_length=100)


class UpdateOrganizationRequest(BaseModel):
    """Request model for updating organization."""
    name: str = Field(..., min_length=1, max_length=255)


class OrganizationResponse(BaseModel):
    """Response model for organization details."""
    id: str
    name: str
    slug: str
    access_code: str
    is_active: bool
    created_at: str

    class Config:
        from_attributes = True


class CreateMemberRequest(BaseModel):
    """Request model for creating a new user and adding to organization."""
    username: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="member")
    email: Optional[str] = None


class AddExistingMemberRequest(BaseModel):
    """Request model for adding existing user to organization."""
    email: EmailStr
    role: str = Field(default="member", pattern="^(owner|admin|member|viewer)$")


class SelfRegisterRequest(BaseModel):
    """Request model for self-registration via organization link."""
    username: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)


class ChangeRoleRequest(BaseModel):
    """Request model for changing member role."""
    role: str = Field(..., pattern="^(owner|admin|member|viewer)$")


class MemberResponse(BaseModel):
    """Response model for organization member."""
    id: str
    username: Optional[str] = None
    email: Optional[str] = None
    full_name: str
    role: str
    department_id: Optional[str] = None
    is_active: bool
    created_at: str

    class Config:
        from_attributes = True


class OrganizationStatsResponse(BaseModel):
    """Response model for organization statistics."""
    total_members: int
    owners: int
    admins: int
    members: int
    viewers: int
    dialogs: int


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    detail: str


# ============================================================
# Router
# ============================================================

router = APIRouter(
    prefix="/organizations",
    tags=["Organizations"]
)


# ============================================================
# Helper Functions
# ============================================================

async def get_org_service(db: AsyncSession = Depends(get_db)) -> OrganizationsService:
    """Get organizations service instance."""
    return OrganizationsService(db)


def check_auth_enabled() -> None:
    """Check if authentication is enabled."""
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is disabled. Set FEATURE_FLAG_AUTH=true to enable."
        )


async def _require_member_access(
    organization_id: str,
    user: User,
    db: AsyncSession,
    required_roles: list = None
) -> tuple:
    """
    Check user has the required role in the org specified by URL path org_id.
    This is used instead of AdminOrOwner/OwnerOnly (which read org from JWT,
    causing failures when the token's org_id differs from the URL path org_id).
    Returns (Organization, Membership).
    """
    if required_roles is None:
        required_roles = ["admin", "owner"]

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    stmt = sa_select(Organization, Membership).join(
        Membership, Membership.organization_id == Organization.id
    ).where(
        Membership.user_id == user.id,
        Membership.organization_id == org_uuid,
        Membership.is_active == True
    )
    result = await db.execute(stmt)
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "Not a member of this organization"}
        )

    organization, membership = row

    if required_roles and membership.role not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": f"Requires role: {' or '.join(required_roles)}"}
        )

    return organization, membership


# ============================================================
# Organization CRUD Endpoints
# ============================================================

@router.post(
    "",
    response_model=OrganizationResponse,
    responses={
        201: {"description": "Organization created"},
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Create organization",
    description="Create a new organization. Authenticated user becomes the owner."
)
async def create_organization(
    data: CreateOrganizationRequest,
    user: User = Depends(require_auth),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Create a new organization.

    The authenticated user automatically becomes the owner.
    Organization slug must be unique.
    """
    check_auth_enabled()

    try:
        organization = await org_service.create_organization(
            name=data.name,
            owner_user_id=user.id,
            slug=data.slug
        )

        return OrganizationResponse(
            id=str(organization.id),
            name=organization.name,
            slug=organization.slug,
            access_code=organization.access_code or "",
            is_active=organization.is_active,
            created_at=organization.created_at.isoformat() if organization.created_at else ""
        )

    except OrganizationAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "slug_exists", "detail": str(e)}
        )


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    responses={
        200: {"description": "Organization details"},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Get organization details",
    description="Get details of a specific organization."
)
async def get_organization(
    organization_id: str,
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Get organization details by ID.

    Does not require membership - used for sharing organization info.
    """
    check_auth_enabled()

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    organization = await org_service.get_organization_by_id(org_uuid)

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": "Organization not found"}
        )

    return OrganizationResponse(
        id=str(organization.id),
        name=organization.name,
        slug=organization.slug,
        access_code=organization.access_code,
        is_active=organization.is_active,
        created_at=organization.created_at.isoformat() if organization.created_at else ""
    )


@router.get(
    "/by-code/{access_code}",
    response_model=OrganizationResponse,
    responses={
        200: {"description": "Organization details"},
        404: {"model": ErrorResponse}
    },
    summary="Get organization by access code",
    description="Get organization details using 6-character access code."
)
async def get_organization_by_code(
    access_code: str,
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Get organization by access code.

    Does not require authentication - used for organization-specific login pages.
    """
    organization = await org_service.get_organization_by_access_code(access_code)

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": "Organization not found"}
        )

    return OrganizationResponse(
        id=str(organization.id),
        name=organization.name,
        slug=organization.slug,
        access_code=organization.access_code,
        is_active=organization.is_active,
        created_at=organization.created_at.isoformat() if organization.created_at else ""
    )


@router.post(
    "/join/{access_code}",
    responses={
        200: {"description": "Successfully registered and joined"},
        400: {"description": "Validation error or user exists"},
        404: {"description": "Organization not found"}
    },
    summary="Self-register and join organization",
    description="Public endpoint — register a new user via organization link."
)
async def self_register_and_join(
    access_code: str,
    data: SelfRegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Self-register a new user and add them to an organization.

    PUBLIC endpoint — no authentication required.
    The user provides the org access code from the link, creates an account,
    and is automatically added as a 'member'. Returns login tokens immediately.
    """
    check_auth_enabled()

    org_service = OrganizationsService(db)
    auth_service = org_service.auth_service

    organization = await org_service.get_organization_by_access_code(access_code.upper())
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Организация с таким кодом не найдена"
        )

    try:
        user = await auth_service.create_user(
            password=data.password,
            full_name=data.full_name,
            username=data.username,
        )
    except ValueError as e:
        if "already exists" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь с таким логином уже существует"
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            role="member",
            is_active=True,
        )
        db.add(membership)
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не удалось добавить в организацию"
        )

    session = await auth_service.create_session(user.id, organization.id)

    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "user": {
            "id": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email or "",
            "is_active": user.is_active,
        },
        "organization": {
            "id": str(organization.id),
            "name": organization.name,
            "slug": organization.slug,
            "role": "member"
        }
    }


@router.put(
    "/{organization_id}",
    response_model=OrganizationResponse,
    responses={
        200: {"description": "Organization updated"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Update organization",
    description="Update organization name. Requires admin or higher role."
)
async def update_organization(
    organization_id: str,
    data: UpdateOrganizationRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Update organization details.

    Requires admin or owner role in the organization.
    """
    check_auth_enabled()

    await _require_member_access(organization_id, user, db, ["admin", "owner"])

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    organization = await org_service.update_organization(org_uuid, name=data.name)

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": "Organization not found"}
        )

    return OrganizationResponse(
        id=str(organization.id),
        name=organization.name,
        slug=organization.slug,
        access_code=organization.access_code or "",
        is_active=organization.is_active,
        created_at=organization.created_at.isoformat() if organization.created_at else ""
    )


@router.delete(
    "/{organization_id}",
    responses={
        200: {"description": "Organization deleted"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Delete organization",
    description="Soft delete an organization. Requires owner role."
)
async def delete_organization(
    organization_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Delete (soft delete) an organization.

    Only organization owner can delete.
    This sets is_active=False - data is preserved.
    """
    check_auth_enabled()

    await _require_member_access(organization_id, user, db, ["owner"])

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    success = await org_service.delete_organization(org_uuid)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": "Organization not found"}
        )

    return {"message": "Organization deleted successfully"}


# ============================================================
# Members Endpoints
# ============================================================

@router.get(
    "/{organization_id}/members",
    response_model=List[MemberResponse],
    responses={
        200: {"description": "List of members"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="List organization members",
    description="Get all members of an organization. Requires member role or higher."
)
async def list_members(
    organization_id: str,
    user: User = Depends(require_auth),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    List all members of the organization.

    Requires being a member of the organization.
    """
    check_auth_enabled()

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    # Check if user is a member
    is_member = await org_service.is_owner(user.id, org_uuid)
    if not is_member:
        has_membership = await org_service.get_membership(org_uuid, user.id)
        if not has_membership or not has_membership.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "forbidden", "detail": "Not a member of this organization"}
            )

    members_data = await org_service.get_organization_members(org_uuid)

    return [
        MemberResponse(
            id=str(member_user.id),
            username=member_user.username,
            email=member_user.email,
            full_name=member_user.full_name,
            role=membership.role,
            department_id=str(membership.department_id) if membership.department_id else None,
            is_active=membership.is_active,
            created_at=member_user.created_at.isoformat() if member_user.created_at else ""
        )
        for member_user, membership in members_data
    ]


@router.post(
    "/{organization_id}/add-member",
    response_model=MemberResponse,
    responses={
        201: {"description": "Member added"},
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Create new user and add to organization",
    description="Create a new user account and add them to the organization. Requires admin role."
)
async def create_member_endpoint(
    organization_id: str,
    data: CreateMemberRequest,
    user: User = Depends(require_auth),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Create a new user and add them to the organization.

    This is the PRIMARY method for adding users - creates account
    directly with email/password. NO email invitation needed.

    Requires admin or owner role.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"create_member called: org={organization_id}, user={user.username}, data={data}")
    check_auth_enabled()

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    # Check if user is member of this org and has admin/owner role
    membership = await org_service.get_membership(org_uuid, user.id)
    if not membership or not membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "You are not a member of this organization"}
        )

    # Check role
    if membership.role not in [UserRole.OWNER.value, UserRole.ADMIN.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "Only admins and owners can add members"}
        )

    try:
        user = await org_service.create_and_add_user(
            organization_id=org_uuid,
            username=data.username,
            password=data.password,
            full_name=data.full_name,
            role=data.role,
            email=data.email
        )

        # Get membership for response
        membership = await org_service.get_membership(org_uuid, user.id)

        return MemberResponse(
            id=str(user.id),
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            role=membership.role if membership else data.role,
            created_at=user.created_at.isoformat() if user.created_at else ""
        )

    except UserAlreadyExistsError as e:
        # User already exists - suggest adding existing user
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "user_exists",
                "detail": str(e),
                "hint": "Use POST /organizations/{id}/add-existing to add existing user"
            }
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "detail": str(e)}
        )


@router.post(
    "/{organization_id}/add-existing",
    response_model=MemberResponse,
    responses={
        200: {"description": "Existing user added"},
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Add existing user to organization",
    description="Add an existing user to the organization. Requires admin role."
)
async def add_existing_member(
    organization_id: str,
    data: AddExistingMemberRequest,
    org_ctx = Depends(AdminOrOwner),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Add an existing user to the organization.

    Use this when the user already has an account.
    For creating new accounts, use POST /organizations/{id}/members.

    Requires admin or owner role.
    """
    check_auth_enabled()

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    # Verify org matches context
    if str(org_ctx.organization.id) != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "Not your organization"}
        )

    try:
        membership = await org_service.add_existing_user(
            organization_id=org_uuid,
            user_email=data.email,
            role=data.role
        )

        # Get user for response
        auth_service = org_service.auth_service
        user = await auth_service.get_user_by_id(membership.user_id)

        return MemberResponse(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            role=membership.role,
            created_at=membership.created_at.isoformat() if membership.created_at else ""
        )

    except MemberNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "user_not_found", "detail": str(e)}
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "detail": str(e)}
        )


@router.delete(
    "/{organization_id}/members/{user_id}",
    responses={
        200: {"description": "Member removed"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Remove member from organization",
    description="Remove a member from the organization. Requires admin role."
)
async def remove_member(
    organization_id: str,
    user_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Remove a member from the organization.

    Requires admin or owner role.
    Cannot remove the last owner.
    """
    check_auth_enabled()

    await _require_member_access(organization_id, user, db, ["admin", "owner"])

    try:
        org_uuid = UUID(organization_id)
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid ID"}
        )

    try:
        success = await org_service.remove_member(org_uuid, user_uuid)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "detail": "Member not found"}
            )

        return {"message": "Member removed successfully"}

    except ValueError as e:
        if "last owner" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "last_owner", "detail": str(e)}
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "detail": str(e)}
        )


@router.patch(
    "/{organization_id}/members/{user_id}/role",
    response_model=MemberResponse,
    responses={
        200: {"description": "Member role updated"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Change member role",
    description="Change a member's role. Requires admin role."
)
async def change_member_role(
    organization_id: str,
    user_id: str,
    data: ChangeRoleRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Change a member's role in the organization.

    Requires admin or owner role.
    Cannot change the last owner to a non-owner role.
    """
    check_auth_enabled()

    await _require_member_access(organization_id, user, db, ["admin", "owner"])

    try:
        org_uuid = UUID(organization_id)
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid ID"}
        )

    try:
        membership = await org_service.change_member_role(
            org_uuid, user_uuid, data.role
        )

        if not membership:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "detail": "Member not found"}
            )

        # Get user for response
        auth_service = org_service.auth_service
        member_user = await auth_service.get_user_by_id(membership.user_id)

        return MemberResponse(
            id=str(member_user.id),
            email=member_user.email,
            full_name=member_user.full_name,
            is_active=member_user.is_active,
            role=membership.role,
            created_at=membership.created_at.isoformat() if membership.created_at else ""
        )

    except ValueError as e:
        if "last owner" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "last_owner", "detail": str(e)}
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "detail": str(e)}
        )


@router.get(
    "/{organization_id}/stats",
    response_model=OrganizationStatsResponse,
    responses={
        200: {"description": "Organization statistics"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    },
    summary="Get organization statistics",
    description="Get statistics about the organization. Requires member role."
)
async def get_organization_stats(
    organization_id: str,
    user: User = Depends(require_auth),
    org_service: OrganizationsService = Depends(get_org_service)
):
    """
    Get organization statistics including member counts and dialog counts.

    Requires being a member of the organization.
    """
    check_auth_enabled()

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "invalid_id", "detail": "Invalid organization ID"}
        )

    # Check if user is a member
    has_membership = await org_service.get_membership(org_uuid, user.id)
    if not has_membership or not has_membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "Not a member of this organization"}
        )

    stats = await org_service.get_organization_stats(org_uuid)

    return OrganizationStatsResponse(**stats)
