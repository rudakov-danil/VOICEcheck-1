"""
Department Management Service.

Provides CRUD operations for departments within organizations,
including head assignment and member assignment.
"""

from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from .models import Department, Membership, User, Organization


class DepartmentsService:
    """Service for managing departments within organizations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_department(
        self,
        organization_id: UUID,
        name: str,
        head_user_id: Optional[UUID] = None
    ) -> Department:
        """Create a new department in the organization."""
        department = Department(
            organization_id=organization_id,
            name=name,
            head_user_id=head_user_id
        )
        self.db.add(department)
        await self.db.commit()
        await self.db.refresh(department)
        return department

    async def get_department(self, department_id: UUID) -> Optional[Department]:
        """Get department by ID."""
        result = await self.db.execute(
            select(Department).where(
                and_(Department.id == department_id, Department.is_active == True)
            )
        )
        return result.scalar_one_or_none()

    async def list_departments(self, organization_id: UUID) -> List[dict]:
        """List all active departments for an organization with head info."""
        result = await self.db.execute(
            select(Department, User).outerjoin(
                User, Department.head_user_id == User.id
            ).where(
                and_(
                    Department.organization_id == organization_id,
                    Department.is_active == True
                )
            ).order_by(Department.name)
        )
        rows = result.all()

        departments = []
        for dept, head_user in rows:
            # Count members in this department
            count_result = await self.db.execute(
                select(func.count(Membership.id)).where(
                    and_(
                        Membership.department_id == dept.id,
                        Membership.is_active == True
                    )
                )
            )
            member_count = count_result.scalar() or 0

            departments.append({
                "id": str(dept.id),
                "name": dept.name,
                "organization_id": str(dept.organization_id),
                "head_user_id": str(dept.head_user_id) if dept.head_user_id else None,
                "head_user_name": head_user.full_name if head_user else None,
                "member_count": member_count,
                "is_active": dept.is_active,
                "created_at": dept.created_at.isoformat() if dept.created_at else ""
            })

        return departments

    async def update_department(
        self,
        department_id: UUID,
        name: Optional[str] = None,
        head_user_id: Optional[UUID] = None
    ) -> Optional[Department]:
        """Update department name and/or head."""
        dept = await self.get_department(department_id)
        if not dept:
            return None

        if name is not None:
            dept.name = name
        if head_user_id is not None:
            dept.head_user_id = head_user_id if str(head_user_id) != '' else None

        await self.db.commit()
        await self.db.refresh(dept)
        return dept

    async def delete_department(self, department_id: UUID) -> bool:
        """Soft delete a department (unlinks members)."""
        dept = await self.get_department(department_id)
        if not dept:
            return False

        dept.is_active = False

        # Unlink members from this department
        result = await self.db.execute(
            select(Membership).where(Membership.department_id == department_id)
        )
        for membership in result.scalars().all():
            membership.department_id = None

        await self.db.commit()
        return True

    async def assign_member(
        self,
        department_id: UUID,
        user_id: UUID,
        organization_id: UUID
    ) -> Optional[Membership]:
        """Assign a member to a department."""
        result = await self.db.execute(
            select(Membership).where(
                and_(
                    Membership.user_id == user_id,
                    Membership.organization_id == organization_id,
                    Membership.is_active == True
                )
            )
        )
        membership = result.scalar_one_or_none()
        if not membership:
            return None

        membership.department_id = department_id
        await self.db.commit()
        await self.db.refresh(membership)
        return membership

    async def remove_member_from_department(
        self,
        user_id: UUID,
        organization_id: UUID
    ) -> Optional[Membership]:
        """Remove a member from their department (set department_id to None)."""
        result = await self.db.execute(
            select(Membership).where(
                and_(
                    Membership.user_id == user_id,
                    Membership.organization_id == organization_id,
                    Membership.is_active == True
                )
            )
        )
        membership = result.scalar_one_or_none()
        if not membership:
            return None

        membership.department_id = None
        await self.db.commit()
        await self.db.refresh(membership)
        return membership
