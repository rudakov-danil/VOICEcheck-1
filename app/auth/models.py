"""
Database models for authentication and authorization system.

This module defines the core database models for the auth system:
- User: Represents a user account with email and password
- Organization: Represents an organization/company
- Membership: Junction table for user-organization relationships with roles
- Session: Represents user sessions for JWT token management

Key Design Decisions:
- NO invitations table - users are created directly by organization owners
- Passwords are hashed using bcrypt
- Sessions track active JWT tokens for logout functionality
- Memberships support RBAC with role-based permissions
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List
from uuid import uuid4

from sqlalchemy import (
    Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index,
    UniqueConstraint, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database.models import Base


class UserRole(str, Enum):
    """
    User roles within an organization.

    Roles define the permissions a user has within an organization context.
    Roles are hierarchical: OWNER > ADMIN > MEMBER > VIEWER.

    OWNER: Full control of the organization, can manage all members and settings
    ADMIN: Can manage dialogs and members, but cannot delete the organization
    MEMBER: Can create and view dialogs within the organization
    VIEWER: Read-only access to dialogs and analytics
    """
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"

    @classmethod
    def all(cls) -> List[str]:
        """Return list of all valid role names."""
        return [r.value for r in cls]

    def can_manage_members(self) -> bool:
        """Check if role can manage organization members."""
        return self in (UserRole.OWNER, UserRole.ADMIN)

    def can_manage_dialogs(self) -> bool:
        """Check if role can create/edit/delete dialogs."""
        return self in (UserRole.OWNER, UserRole.ADMIN, UserRole.MEMBER)

    def can_view_dialogs(self) -> bool:
        """Check if role can view dialogs and analytics."""
        return self in (UserRole.OWNER, UserRole.ADMIN, UserRole.MEMBER, UserRole.VIEWER)


class User(Base):
    """
    User account model.

    Represents a user in the system with username/email authentication.
    A user can belong to multiple organizations via Membership records.

    Attributes:
        id: Unique user identifier (UUID)
        username: Unique username for login (organization-specific)
        email: User email address (optional, unique if provided)
        password_hash: Bcrypt hash of user password
        full_name: User's full display name
        is_active: Whether the account is active (for soft delete/bans)
        created_at: Account creation timestamp
        updated_at: Last update timestamp
        last_login_at: Last successful login timestamp

    Relationships:
        memberships: List of organization memberships
        sessions: List of active sessions
        created_dialogs: Dialogs created by this user
    """

    __tablename__ = "users"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    # Authentication fields
    username = Column(String(100), nullable=True, unique=True, index=True,
                     comment="Unique username for login (organization-specific)")
    email = Column(String(255), nullable=True, unique=True, index=True,
                   comment="User email address (optional, unique if provided)")
    password_hash = Column(String(255), nullable=False,
                          comment="Bcrypt hash of user password")

    # Profile fields
    full_name = Column(String(255), nullable=False,
                      comment="User's full display name")

    # Status fields
    is_active = Column(Boolean, nullable=False, default=True,
                      comment="Whether the account is active")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       comment="Account creation timestamp")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(),
                       comment="Last update timestamp")
    last_login_at = Column(DateTime(timezone=True), nullable=True,
                          comment="Last successful login timestamp")

    # Relationships
    memberships = relationship("Membership", back_populates="user",
                              cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user",
                           cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        """
        Hash and set the user's password.

        Args:
            password: Plain text password to hash
        """
        import bcrypt
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def verify_password(self, password: str) -> bool:
        """
        Verify a password against the stored hash.

        Args:
            password: Plain text password to verify

        Returns:
            True if password matches, False otherwise
        """
        import bcrypt
        try:
            return bcrypt.checkpw(
                password.encode('utf-8'),
                self.password_hash.encode('utf-8')
            )
        except Exception:
            return False

    def get_organizations(self, active_only: bool = True) -> List['Organization']:
        """
        Get all organizations this user belongs to.

        Args:
            active_only: If True, only return active memberships

        Returns:
            List of Organization objects
        """
        query = [m.organization for m in self.memberships]
        if active_only:
            query = [m.organization for m in self.memberships if m.is_active]
        return query

    def has_role_in_organization(self, organization_id, role: UserRole) -> bool:
        """
        Check if user has a specific role in an organization.

        Args:
            organization_id: UUID of the organization
            role: Role to check for

        Returns:
            True if user has the role, False otherwise
        """
        for membership in self.memberships:
            if membership.organization_id == organization_id:
                return membership.role == role
        return False


class Organization(Base):
    """
    Organization model.

    Represents an organization or company in the system.
    Organizations contain users via Membership records and own Dialog records.

    Attributes:
        id: Unique organization identifier (UUID)
        name: Organization name (not unique, multiple orgs can have same name)
        slug: URL-friendly unique identifier for the organization
        access_code: Unique code for organization-specific login
        is_active: Whether the organization is active
        created_at: Organization creation timestamp
        updated_at: Last update timestamp

    Relationships:
        memberships: List of user memberships
        dialogs: Dialogs owned by this organization
    """

    __tablename__ = "organizations"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    # Organization details
    name = Column(String(255), nullable=False,
                  comment="Organization display name")
    slug = Column(String(100), nullable=False, unique=True, index=True,
                  comment="URL-friendly unique identifier")
    access_code = Column(String(20), nullable=False, unique=True, index=True,
                        comment="Unique code for organization login")

    # Status
    is_active = Column(Boolean, nullable=False, default=True,
                      comment="Whether the organization is active")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       comment="Organization creation timestamp")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(),
                       comment="Last update timestamp")

    # Relationships
    memberships = relationship("Membership", back_populates="organization",
                              cascade="all, delete-orphan")
    departments = relationship("Department", back_populates="organization",
                              cascade="all, delete-orphan")

    def get_owner(self) -> Optional[User]:
        """Get the owner user of this organization."""
        for membership in self.memberships:
            if membership.role == UserRole.OWNER and membership.is_active:
                return membership.user
        return None

    def get_active_members(self) -> List[User]:
        """Get all active members of the organization."""
        return [m.user for m in self.memberships if m.is_active]

    def member_count(self) -> int:
        """Get count of active members."""
        return sum(1 for m in self.memberships if m.is_active)


class Department(Base):
    """Department within an organization, optionally led by a user."""

    __tablename__ = "departments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    name = Column(String(255), nullable=False)
    head_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                         nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="departments")
    head_user = relationship("User", foreign_keys=[head_user_id])
    members = relationship("Membership", back_populates="department",
                          foreign_keys="Membership.department_id")


class Membership(Base):
    """Membership model for user-organization relationship with optional department."""

    __tablename__ = "memberships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    role = Column(String(50), nullable=False, default=UserRole.MEMBER.value)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="memberships")
    organization = relationship("Organization", back_populates="memberships")
    department = relationship("Department", back_populates="members",
                            foreign_keys=[department_id])

    roles_list = "', '".join(UserRole.all())
    __table_args__ = (
        UniqueConstraint('user_id', 'organization_id', name='uq_user_organization'),
        CheckConstraint(
            f"role IN ('{roles_list}')",
            name='ck_valid_role'
        )
    )


class Session(Base):
    """
    Session model for JWT token management.

    Tracks active user sessions for logout functionality and security monitoring.
    Each login creates a new session record.

    Attributes:
        id: Unique session identifier (UUID)
        user_id: Reference to the user
        token_jti: JWT Token ID (jti claim) for session tracking
        refresh_token_jti: Refresh token JTI
        organization_id: Currently selected organization (nullable)
        expires_at: Session expiration time
        is_active: Whether the session is active
        created_at: Session creation timestamp

    Relationships:
        user: Reference to the User model
    """

    __tablename__ = "sessions"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    # Foreign key
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False, index=True, comment="Reference to user")

    # Token tracking
    token_jti = Column(String(255), nullable=False, unique=True, index=True,
                      comment="JWT Token ID for revocation")
    refresh_token_jti = Column(String(255), nullable=True, unique=True, index=True,
                              comment="Refresh Token ID for revocation")

    # Context
    organization_id = Column(UUID(as_uuid=True), nullable=True, index=True,
                             comment="Currently selected organization ID")

    # Expiration
    expires_at = Column(DateTime(timezone=True), nullable=False,
                       comment="Session expiration time")

    # Status
    is_active = Column(Boolean, nullable=False, default=True,
                      comment="Whether the session is active")

    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       comment="Session creation timestamp")

    # Relationships
    user = relationship("User", back_populates="sessions")

    def is_valid(self) -> bool:
        """Check if session is currently valid (active and not expired)."""
        return self.is_active and (
            self.expires_at.replace(tzinfo=None) > datetime.utcnow()
            if self.expires_at.tzinfo is not None
            else self.expires_at > datetime.utcnow()
        )

    def revoke(self) -> None:
        """Revoke (deactivate) the session."""
        self.is_active = False
