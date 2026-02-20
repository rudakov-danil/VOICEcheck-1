"""
Organization Management Service.

Provides functionality for:
- Organization CRUD operations
- Direct user creation by organization owners (NO email invitations)
- Membership management (add, remove, change roles)
- RBAC permission checks
- Organization member listing

Key design: Users are created directly by org owners with email/password.
No invitation mechanism - accounts are ready immediately.
"""

from typing import Optional, List
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.exc import IntegrityError

from .models import User, Organization, Membership, Session, UserRole
from .service import AuthService
from ..database.models import Dialog


class OrganizationAlreadyExistsError(Exception):
    """Raised when trying to create an organization with duplicate slug."""
    pass


class UserAlreadyExistsError(Exception):
    """Raised when trying to create a user that already exists."""
    pass


class MemberNotFoundError(Exception):
    """Raised when trying to access a non-existent member."""
    pass


class InsufficientPermissionsError(Exception):
    """Raised when user lacks required permissions."""
    pass


class OrganizationsService:
    """
    Service for managing organizations and their members.

    Handles all organization-related operations including
    creating organizations, managing memberships, and checking permissions.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize organizations service.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self.auth_service = AuthService(db)

    # ============================================================
    # Organization CRUD
    # ============================================================

    async def create_organization(
        self,
        name: str,
        owner_user_id: UUID,
        slug: Optional[str] = None
    ) -> Organization:
        """
        Create a new organization with specified owner.

        Args:
            name: Organization display name
            owner_user_id: UUID of the user who will be owner
            slug: Optional URL-friendly identifier (auto-generated if None)

        Returns:
            Created Organization object

        Raises:
            OrganizationAlreadyExistsError: If slug already exists
        """
        # Check user exists
        owner = await self.auth_service.get_user_by_id(owner_user_id)
        if not owner:
            raise ValueError("Owner user not found")

        # Generate slug if not provided
        if not slug:
            slug = self._generate_slug(name)

        # Check slug uniqueness
        existing = await self.get_organization_by_slug(slug)
        if existing:
            raise OrganizationAlreadyExistsError(
                f"Organization with slug '{slug}' already exists"
            )

        # Generate unique access code
        access_code = await self._generate_access_code()

        # Create organization
        organization = Organization(
            name=name,
            slug=slug,
            access_code=access_code
        )

        self.db.add(organization)
        await self.db.flush()  # Get ID without committing

        # Create owner membership
        membership = Membership(
            user_id=owner_user_id,
            organization_id=organization.id,
            role=UserRole.OWNER.value
        )

        self.db.add(membership)
        await self.db.commit()
        await self.db.refresh(organization)

        return organization

    async def get_organization_by_id(
        self,
        organization_id: UUID
    ) -> Optional[Organization]:
        """
        Get organization by ID.

        Args:
            organization_id: UUID of the organization

        Returns:
            Organization object or None
        """
        result = await self.db.execute(
            select(Organization).where(
                and_(
                    Organization.id == organization_id,
                    Organization.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_organization_by_slug(self, slug: str) -> Optional[Organization]:
        """
        Get organization by slug.

        Args:
            slug: URL-friendly organization identifier

        Returns:
            Organization object or None
        """
        result = await self.db.execute(
            select(Organization).where(
                and_(
                    Organization.slug == slug,
                    Organization.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_organization_by_access_code(self, access_code: str) -> Optional[Organization]:
        """
        Get organization by access code.

        Args:
            access_code: 6-character organization access code

        Returns:
            Organization object or None
        """
        result = await self.db.execute(
            select(Organization).where(
                and_(
                    Organization.access_code == access_code.upper(),
                    Organization.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()

    async def update_organization(
        self,
        organization_id: UUID,
        name: Optional[str] = None
    ) -> Optional[Organization]:
        """
        Update organization details.

        Args:
            organization_id: UUID of the organization
            name: New name (optional)

        Returns:
            Updated Organization or None if not found
        """
        organization = await self.get_organization_by_id(organization_id)
        if not organization:
            return None

        if name:
            organization.name = name

        await self.db.commit()
        await self.db.refresh(organization)

        return organization

    async def delete_organization(self, organization_id: UUID) -> bool:
        """
        Soft delete an organization (set is_active=False).

        Args:
            organization_id: UUID of the organization

        Returns:
            True if deleted, False if not found
        """
        organization = await self.get_organization_by_id(organization_id)
        if not organization:
            return False

        organization.is_active = False
        await self.db.commit()

        return True

    # ============================================================
    # Member Management (Direct User Creation - NO Invitations)
    # ============================================================

    async def create_and_add_user(
        self,
        organization_id: UUID,
        username: str,
        password: str,
        full_name: str,
        role: str = UserRole.MEMBER.value,
        email: Optional[str] = None,
        created_by_user_id: Optional[UUID] = None
    ) -> User:
        """
        Create a new user and add them to the organization.

        This is the PRIMARY method for adding users to organizations.
        NO email invitation - account is created and ready immediately.

        Args:
            organization_id: UUID of the organization
            username: Username for login (required)
            password: User password (plain text, will be hashed)
            full_name: User's full display name
            role: Role to assign (default: member)
            email: User email (optional)
            created_by_user_id: UUID of user creating this account

        Returns:
            Created User object

        Raises:
            UserAlreadyExistsError: If username already exists
            ValueError: If role is invalid
        """
        # Validate role
        if role not in UserRole.all():
            raise ValueError(f"Invalid role: {role}")

        # Check organization exists
        organization = await self.get_organization_by_id(organization_id)
        if not organization:
            raise ValueError("Organization not found")

        # Create user using auth service
        try:
            user = await self.auth_service.create_user(
                username=username,
                password=password,
                full_name=full_name,
                email=email
            )
        except ValueError as e:
            if "already exists" in str(e):
                raise UserAlreadyExistsError(
                    f"User with username '{username}' already exists"
                )
            raise

        # Add membership to organization
        await self.add_member(
            organization_id=organization_id,
            user_id=user.id,
            role=role
        )

        return user

    async def add_existing_user(
        self,
        organization_id: UUID,
        user_email: str,
        role: str = UserRole.MEMBER.value
    ) -> Membership:
        """
        Add an existing user to an organization.

        Args:
            organization_id: UUID of the organization
            user_email: Email of existing user
            role: Role to assign

        Returns:
            Created Membership object

        Raises:
            MemberNotFoundError: If user not found
            ValueError: If user is already a member
        """
        # Find user by email
        user = await self.auth_service.get_user_by_email(user_email)
        if not user:
            raise MemberNotFoundError(
                f"User with email '{user_email}' not found"
            )

        # Check if already member
        existing = await self.get_membership(organization_id, user.id)
        if existing:
            if existing.is_active:
                raise ValueError("User is already a member of this organization")
            # Reactivate
            existing.is_active = True
            existing.role = role
            await self.db.commit()
            return existing

        # Create membership
        return await self.add_member(organization_id, user.id, role)

    async def add_member(
        self,
        organization_id: UUID,
        user_id: UUID,
        role: str = UserRole.MEMBER.value
    ) -> Membership:
        """
        Create a membership record.

        Args:
            organization_id: UUID of the organization
            user_id: UUID of the user
            role: Role to assign

        Returns:
            Created Membership object
        """
        membership = Membership(
            user_id=user_id,
            organization_id=organization_id,
            role=role
        )

        self.db.add(membership)
        await self.db.commit()
        await self.db.refresh(membership)

        return membership

    async def remove_member(
        self,
        organization_id: UUID,
        user_id: UUID
    ) -> bool:
        """
        Remove a member from the organization (soft delete).

        Args:
            organization_id: UUID of the organization
            user_id: UUID of the user to remove

        Returns:
            True if removed, False if membership not found
        """
        membership = await self.get_membership(organization_id, user_id)
        if not membership:
            return False

        # Can't remove the last owner
        if membership.role == UserRole.OWNER.value:
            owner_count = await self.count_members_by_role(
                organization_id, UserRole.OWNER
            )
            if owner_count <= 1:
                raise ValueError(
                    "Cannot remove the last owner of an organization"
                )

        membership.is_active = False
        await self.db.commit()

        return True

    async def change_member_role(
        self,
        organization_id: UUID,
        user_id: UUID,
        new_role: str
    ) -> Optional[Membership]:
        """
        Change a member's role.

        Args:
            organization_id: UUID of the organization
            user_id: UUID of the user
            new_role: New role to assign

        Returns:
            Updated Membership or None

        Raises:
            ValueError: If attempting to change last owner to non-owner
        """
        if new_role not in UserRole.all():
            raise ValueError(f"Invalid role: {new_role}")

        membership = await self.get_membership(organization_id, user_id)
        if not membership:
            return None

        # Check if this would leave org without owner
        old_role = membership.role
        if old_role == UserRole.OWNER.value and new_role != UserRole.OWNER.value:
            owner_count = await self.count_members_by_role(
                organization_id, UserRole.OWNER
            )
            if owner_count <= 1:
                raise ValueError(
                    "Cannot change the last owner's role"
                )

        membership.role = new_role
        await self.db.commit()
        await self.db.refresh(membership)

        return membership

    async def get_membership(
        self,
        organization_id: UUID,
        user_id: UUID
    ) -> Optional[Membership]:
        """
        Get membership record for a user in an organization.

        Args:
            organization_id: UUID of the organization
            user_id: UUID of the user

        Returns:
            Membership object or None
        """
        result = await self.db.execute(
            select(Membership).where(
                and_(
                    Membership.organization_id == organization_id,
                    Membership.user_id == user_id
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_organization_members(
        self,
        organization_id: UUID,
        active_only: bool = True
    ) -> List[tuple[User, Membership]]:
        """
        Get all members of an organization.

        Args:
            organization_id: UUID of the organization
            active_only: Only return active members

        Returns:
            List of (User, Membership) tuples
        """
        query = select(User, Membership).join(
            Membership,
            Membership.user_id == User.id
        ).where(
            Membership.organization_id == organization_id
        )

        if active_only:
            query = query.where(Membership.is_active == True)

        result = await self.db.execute(query)
        return result.all()

    async def count_members_by_role(
        self,
        organization_id: UUID,
        role: UserRole
    ) -> int:
        """
        Count members with a specific role.

        Args:
            organization_id: UUID of the organization
            role: Role to count

        Returns:
            Number of active members with this role
        """
        result = await self.db.execute(
            select(func.count(Membership.id)).where(
                and_(
                    Membership.organization_id == organization_id,
                    Membership.role == role.value,
                    Membership.is_active == True
                )
            )
        )
        return result.scalar() or 0

    # ============================================================
    # Permission Checks
    # ============================================================

    async def check_permission(
        self,
        user_id: UUID,
        organization_id: UUID,
        required_role: UserRole
    ) -> bool:
        """
        Check if user has at least the required role in organization.

        Args:
            user_id: UUID of the user
            organization_id: UUID of the organization
            required_role: Minimum required role

        Returns:
            True if user has sufficient permissions
        """
        membership = await self.get_membership(organization_id, user_id)

        if not membership or not membership.is_active:
            return False

        role_hierarchy = {
            UserRole.OWNER: 4,
            UserRole.ADMIN: 3,
            UserRole.MEMBER: 2,
            UserRole.VIEWER: 1
        }

        user_level = role_hierarchy.get(UserRole(membership.role), 0)
        required_level = role_hierarchy.get(required_role, 0)

        return user_level >= required_level

    async def can_manage_members(
        self,
        user_id: UUID,
        organization_id: UUID
    ) -> bool:
        """Check if user can manage organization members."""
        return await self.check_permission(
            user_id, organization_id, UserRole.ADMIN
        )

    async def can_manage_dialogs(
        self,
        user_id: UUID,
        organization_id: UUID
    ) -> bool:
        """Check if user can manage dialogs."""
        return await self.check_permission(
            user_id, organization_id, UserRole.MEMBER
        )

    async def can_view_dialogs(
        self,
        user_id: UUID,
        organization_id: UUID
    ) -> bool:
        """Check if user can view dialogs."""
        return await self.check_permission(
            user_id, organization_id, UserRole.VIEWER
        )

    async def is_owner(
        self,
        user_id: UUID,
        organization_id: UUID
    ) -> bool:
        """Check if user is organization owner."""
        membership = await self.get_membership(organization_id, user_id)
        return (
            membership is not None
            and membership.is_active
            and membership.role == UserRole.OWNER.value
        )

    # ============================================================
    # Organization Statistics
    # ============================================================

    async def get_organization_stats(
        self,
        organization_id: UUID
    ) -> dict:
        """
        Get statistics for an organization.

        Args:
            organization_id: UUID of the organization

        Returns:
            Dict with organization statistics
        """
        # Member counts
        total_members = await self.count_members_by_role(
            organization_id, UserRole.MEMBER
        )
        admin_count = await self.count_members_by_role(
            organization_id, UserRole.ADMIN
        )
        owner_count = await self.count_members_by_role(
            organization_id, UserRole.OWNER
        )
        viewer_count = await self.count_members_by_role(
            organization_id, UserRole.VIEWER
        )

        # Dialog count
        dialog_result = await self.db.execute(
            select(func.count(Dialog.id)).where(
                and_(
                    Dialog.owner_type == "organization",
                    Dialog.owner_id == organization_id
                )
            )
        )
        dialog_count = dialog_result.scalar() or 0

        return {
            "total_members": total_members + admin_count + owner_count + viewer_count,
            "owners": owner_count,
            "admins": admin_count,
            "members": total_members,
            "viewers": viewer_count,
            "dialogs": dialog_count
        }

    # ============================================================
    # Utility Methods
    # ============================================================

    def _generate_slug(self, name: str) -> str:
        """
        Generate URL-friendly slug from name.

        Args:
            name: Organization name

        Returns:
            URL-safe slug with random suffix
        """
        import re
        base = re.sub(r'[^\w\s-]', '', name).strip().lower()
        base = re.sub(r'[-\s]+', '-', base)
        suffix = uuid4().hex[:6]
        return f"{base}-{suffix}"

    async def _generate_access_code(self) -> str:
        """
        Generate unique 6-character access code for organization.

        Returns:
            6-character uppercase code (letters + numbers)
        """
        import random
        import string

        while True:
            # Generate 6-character code
            code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))

            # Check uniqueness
            existing = await self.db.execute(
                select(Organization.id).where(Organization.access_code == code)
            )
            if not existing.scalar_one_or_none():
                return code

    async def get_user_organizations(
        self,
        user_id: UUID
    ) -> List[Organization]:
        """
        Get all organizations user belongs to.

        Args:
            user_id: UUID of the user

        Returns:
            List of Organization objects
        """
        return await self.auth_service.get_user_organizations(user_id)
