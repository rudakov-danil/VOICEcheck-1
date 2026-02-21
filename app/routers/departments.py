"""
Departments API Router.

Provides CRUD endpoints for departments within organizations,
including member assignment and head assignment.
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..auth.dependencies import require_auth
from ..auth.models import User, UserRole
from ..auth.departments import DepartmentsService
from ..auth.organizations import OrganizationsService


router = APIRouter(
    prefix="/organizations/{organization_id}/departments",
    tags=["Departments"]
)


# Request/Response models

class CreateDepartmentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    head_user_id: Optional[str] = None


class UpdateDepartmentRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    head_user_id: Optional[str] = None


class AssignMemberRequest(BaseModel):
    user_id: str


class DepartmentResponse(BaseModel):
    id: str
    name: str
    organization_id: str
    head_user_id: Optional[str] = None
    head_user_name: Optional[str] = None
    member_count: int = 0
    is_active: bool = True
    created_at: str = ""


# Helper

async def get_services(db: AsyncSession = Depends(get_db)):
    return DepartmentsService(db), OrganizationsService(db)


async def check_admin_access(organization_id: str, user: User, org_service: OrganizationsService):
    """Verify user has admin+ role in the organization."""
    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid organization ID")

    membership = await org_service.get_membership(org_uuid, user.id)
    if not membership or not membership.is_active:
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    if membership.role not in [UserRole.OWNER.value, UserRole.ADMIN.value]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return org_uuid


# Endpoints

@router.get("", response_model=List[DepartmentResponse])
async def list_departments(
    organization_id: str,
    user: User = Depends(require_auth),
    services: tuple = Depends(get_services)
):
    """List all departments in the organization."""
    dept_service, org_service = services

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid organization ID")

    # Any member can view departments
    membership = await org_service.get_membership(org_uuid, user.id)
    if not membership or not membership.is_active:
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    departments = await dept_service.list_departments(org_uuid)
    return departments


@router.post("", response_model=DepartmentResponse, status_code=201)
async def create_department(
    organization_id: str,
    data: CreateDepartmentRequest,
    user: User = Depends(require_auth),
    services: tuple = Depends(get_services)
):
    """Create a new department. Requires admin or owner role."""
    dept_service, org_service = services
    org_uuid = await check_admin_access(organization_id, user, org_service)

    head_uuid = UUID(data.head_user_id) if data.head_user_id else None

    dept = await dept_service.create_department(
        organization_id=org_uuid,
        name=data.name,
        head_user_id=head_uuid
    )

    return DepartmentResponse(
        id=str(dept.id),
        name=dept.name,
        organization_id=str(dept.organization_id),
        head_user_id=str(dept.head_user_id) if dept.head_user_id else None,
        member_count=0,
        is_active=dept.is_active,
        created_at=dept.created_at.isoformat() if dept.created_at else ""
    )


@router.put("/{department_id}", response_model=DepartmentResponse)
async def update_department(
    organization_id: str,
    department_id: str,
    data: UpdateDepartmentRequest,
    user: User = Depends(require_auth),
    services: tuple = Depends(get_services)
):
    """Update a department. Requires admin or owner role."""
    dept_service, org_service = services
    await check_admin_access(organization_id, user, org_service)

    try:
        dept_uuid = UUID(department_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid department ID")

    head_uuid = UUID(data.head_user_id) if data.head_user_id else None

    dept = await dept_service.update_department(
        department_id=dept_uuid,
        name=data.name,
        head_user_id=head_uuid
    )

    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    departments = await dept_service.list_departments(UUID(organization_id))
    dept_data = next((d for d in departments if d['id'] == department_id), None)

    if dept_data:
        return DepartmentResponse(**dept_data)

    return DepartmentResponse(
        id=str(dept.id),
        name=dept.name,
        organization_id=str(dept.organization_id),
        head_user_id=str(dept.head_user_id) if dept.head_user_id else None,
        is_active=dept.is_active,
        created_at=dept.created_at.isoformat() if dept.created_at else ""
    )


@router.delete("/{department_id}")
async def delete_department(
    organization_id: str,
    department_id: str,
    user: User = Depends(require_auth),
    services: tuple = Depends(get_services)
):
    """Delete a department. Requires admin or owner role."""
    dept_service, org_service = services
    await check_admin_access(organization_id, user, org_service)

    try:
        dept_uuid = UUID(department_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid department ID")

    success = await dept_service.delete_department(dept_uuid)
    if not success:
        raise HTTPException(status_code=404, detail="Department not found")

    return {"message": "Department deleted"}


@router.post("/{department_id}/members")
async def assign_member_to_department(
    organization_id: str,
    department_id: str,
    data: AssignMemberRequest,
    user: User = Depends(require_auth),
    services: tuple = Depends(get_services)
):
    """Assign a member to a department. Requires admin or owner role."""
    dept_service, org_service = services
    org_uuid = await check_admin_access(organization_id, user, org_service)

    try:
        dept_uuid = UUID(department_id)
        user_uuid = UUID(data.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID")

    membership = await dept_service.assign_member(dept_uuid, user_uuid, org_uuid)
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in organization")

    return {"message": "Member assigned to department"}


@router.delete("/{department_id}/members/{user_id}")
async def remove_member_from_department(
    organization_id: str,
    department_id: str,
    user_id: str,
    user: User = Depends(require_auth),
    services: tuple = Depends(get_services)
):
    """Remove a member from a department. Requires admin or owner role."""
    dept_service, org_service = services
    org_uuid = await check_admin_access(organization_id, user, org_service)

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    membership = await dept_service.remove_member_from_department(user_uuid, org_uuid)
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    return {"message": "Member removed from department"}
