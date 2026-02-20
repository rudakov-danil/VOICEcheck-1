"""
Authentication Service.

Provides core authentication functionality including:
- User registration and authentication
- JWT token generation and validation
- Session management
- Password hashing and verification
- Organization selection context

This service is used by API endpoints to handle all auth operations.
"""

from jose import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from uuid import uuid4, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError

from ..database.models import Base
from .models import User, Organization, Membership, Session, UserRole
from ..config import settings


class AuthService:
    """
    Service for handling authentication and authorization operations.

    Provides methods for user registration, login, token management,
    and session handling with JWT tokens.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize auth service with database session.

        Args:
            db: SQLAlchemy async session for database operations
        """
        self.db = db

    # ============================================================
    # User Operations
    # ============================================================

    async def create_user(
        self,
        password: str,
        full_name: str,
        username: Optional[str] = None,
        email: Optional[str] = None
    ) -> User:
        """
        Create a new user account.

        Args:
            password: Plain text password (will be hashed)
            full_name: User's full display name
            username: Unique username (required for organization members)
            email: User email address (optional, unique if provided)

        Returns:
            Created User object

        Raises:
            ValueError: If username/email already exists or password is invalid
        """
        # Validate password
        self._validate_password(password)

        # At least one of username or email must be provided
        if not username and not email:
            raise ValueError("At least username or email must be provided")

        # Check if username already exists
        if username:
            existing = await self.get_user_by_username(username)
            if existing:
                raise ValueError("User with this username already exists")

        # Check if email already exists
        if email:
            existing = await self.get_user_by_email(email)
            if existing:
                raise ValueError("User with this email already exists")

        # Create user
        user = User(
            username=username,
            email=email,
            full_name=full_name
        )
        user.set_password(password)

        self.db.add(user)
        try:
            await self.db.commit()
            await self.db.refresh(user)
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("User with this username or email already exists")

        return user

    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """
        Get user by ID.

        Args:
            user_id: UUID of the user

        Returns:
            User object or None if not found
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email address.

        Args:
            email: User email address

        Returns:
            User object or None if not found
        """
        result = await self.db.execute(
            select(User).where(
                and_(User.email == email, User.is_active == True)
            )
        )
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Get user by username.

        Args:
            username: User username

        Returns:
            User object or None if not found
        """
        result = await self.db.execute(
            select(User).where(
                and_(User.username == username, User.is_active == True)
            )
        )
        return result.scalar_one_or_none()

    async def update_last_login(self, user: User) -> None:
        """
        Update user's last login timestamp.

        Args:
            user: User object to update
        """
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()

    # ============================================================
    # Authentication Operations
    # ============================================================

    async def authenticate(
        self,
        email: str,
        password: str
    ) -> Optional[User]:
        """
        Authenticate user with email and password.

        Args:
            email: User email address
            password: Plain text password

        Returns:
            User object if authentication successful, None otherwise
        """
        user = await self.get_user_by_email(email)
        if not user:
            return None

        if not user.verify_password(password):
            return None

        return user

    async def authenticate_by_username(
        self,
        username: str,
        password: str
    ) -> Optional[User]:
        """
        Authenticate user with username and password.

        Args:
            username: User username
            password: Plain text password

        Returns:
            User object if authentication successful, None otherwise
        """
        user = await self.get_user_by_username(username)
        if not user:
            return None

        if not user.verify_password(password):
            return None

        return user

    # ============================================================
    # Token Operations
    # ============================================================

    def create_access_token(
        self,
        user_id: UUID,
        organization_id: Optional[UUID] = None
    ) -> tuple[str, str]:
        """
        Create JWT access token.

        Args:
            user_id: UUID of the user
            organization_id: Optional currently selected organization

        Returns:
            Tuple of (token_string, jti_claim)
        """
        jti = str(uuid4())
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        payload = {
            "sub": str(user_id),
            "jti": jti,
            "iat": now.timestamp(),
            "exp": exp.timestamp(),
            "type": "access"
        }

        if organization_id:
            payload["org_id"] = str(organization_id)

        token = jwt.encode(
            payload,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )

        return token, jti

    def create_refresh_token(
        self,
        user_id: UUID
    ) -> tuple[str, str]:
        """
        Create JWT refresh token.

        Args:
            user_id: UUID of the user

        Returns:
            Tuple of (token_string, jti_claim)
        """
        jti = str(uuid4())
        now = datetime.now(timezone.utc)
        exp = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

        payload = {
            "sub": str(user_id),
            "jti": jti,
            "iat": now.timestamp(),
            "exp": exp.timestamp(),
            "type": "refresh"
        }

        token = jwt.encode(
            payload,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )

        return token, jti

    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decode and validate JWT token.

        Args:
            token: JWT token string

        Returns:
            Decoded token payload

        Raises:
            ValueError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {str(e)}")

    def verify_token_type(self, payload: Dict[str, Any], token_type: str) -> bool:
        """
        Verify token has correct type claim.

        Args:
            payload: Decoded token payload
            token_type: Expected token type ("access" or "refresh")

        Returns:
            True if type matches, False otherwise
        """
        return payload.get("type") == token_type

    # ============================================================
    # Session Operations
    # ============================================================

    async def create_session(
        self,
        user_id: UUID,
        organization_id: Optional[UUID] = None
    ) -> Session:
        """
        Create a new session with access and refresh tokens.

        Args:
            user_id: UUID of the user
            organization_id: Optional selected organization

        Returns:
            Created Session object with tokens
        """
        # Create tokens
        access_token, access_jti = self.create_access_token(user_id, organization_id)
        refresh_token, refresh_jti = self.create_refresh_token(user_id)

        # Calculate expiration
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

        # Create session record
        session = Session(
            user_id=user_id,
            token_jti=access_jti,
            refresh_token_jti=refresh_jti,
            organization_id=organization_id,
            expires_at=expires_at
        )

        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        # Attach tokens to session object (not stored in DB)
        session.access_token = access_token
        session.refresh_token = refresh_token

        return session

    async def get_session_by_jti(self, jti: str) -> Optional[Session]:
        """
        Get session by access token JTI.

        Args:
            jti: JWT ID claim from token

        Returns:
            Session object or None if not found
        """
        result = await self.db.execute(
            select(Session).where(
                and_(
                    Session.token_jti == jti,
                    Session.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_session_by_refresh_jti(self, jti: str) -> Optional[Session]:
        """
        Get session by refresh token JTI.

        Args:
            jti: JWT ID claim from refresh token

        Returns:
            Session object or None if not found
        """
        result = await self.db.execute(
            select(Session).where(
                and_(
                    Session.refresh_token_jti == jti,
                    Session.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()

    async def revoke_session(self, session: Session) -> None:
        """
        Revoke (deactivate) a session.

        Args:
            session: Session object to revoke
        """
        session.is_active = False
        await self.db.commit()

    async def revoke_user_sessions(
        self,
        user_id: UUID,
        exclude_session_id: Optional[UUID] = None
    ) -> int:
        """
        Revoke all sessions for a user.

        Args:
            user_id: UUID of the user
            exclude_session_id: Optional session to keep active

        Returns:
            Number of sessions revoked
        """
        query = select(Session).where(
            and_(
                Session.user_id == user_id,
                Session.is_active == True
            )
        )

        result = await self.db.execute(query)
        sessions = result.scalars().all()

        count = 0
        for session in sessions:
            if exclude_session_id and session.id == exclude_session_id:
                continue
            session.is_active = False
            count += 1

        await self.db.commit()
        return count

    async def cleanup_expired_sessions(self) -> int:
        """
        Delete expired sessions from database.

        Returns:
            Number of sessions deleted
        """
        from sqlalchemy import delete

        stmt = delete(Session).where(
            Session.expires_at < datetime.now(timezone.utc)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    # ============================================================
    # Login/Logout Operations
    # ============================================================

    async def login(
        self,
        email: str,
        password: str,
        organization_id: Optional[UUID] = None
    ) -> tuple[Session, User]:
        """
        Authenticate user and create session.

        Args:
            email: User email address
            password: Plain text password
            organization_id: Optional organization to select after login

        Returns:
            Tuple of (Session object, User object)

        Raises:
            ValueError: If authentication fails
        """
        user = await self.authenticate(email, password)
        if not user:
            raise ValueError("Invalid email or password")

        # Verify organization membership if specified
        if organization_id:
            if not await self.is_organization_member(user.id, organization_id):
                raise ValueError("User is not a member of this organization")

        # Update last login
        await self.update_last_login(user)

        # Create session
        session = await self.create_session(user.id, organization_id)

        return session, user

    async def login_with_username(
        self,
        username: str,
        password: str,
        organization_id: UUID
    ) -> tuple[Session, User]:
        """
        Authenticate user with username and create session.

        Args:
            username: User username
            password: Plain text password
            organization_id: Organization to select (required for username login)

        Returns:
            Tuple of (Session object, User object)

        Raises:
            ValueError: If authentication fails
        """
        user = await self.authenticate_by_username(username, password)
        if not user:
            raise ValueError("Invalid username or password")

        # Verify organization membership
        if not await self.is_organization_member(user.id, organization_id):
            raise ValueError("User is not a member of this organization")

        # Update last login
        await self.update_last_login(user)

        # Create session with organization
        session = await self.create_session(user.id, organization_id)

        return session, user

    async def logout(self, jti: str) -> bool:
        """
        Logout user by revoking their session.

        Args:
            jti: JWT ID claim from access token

        Returns:
            True if session was revoked, False otherwise
        """
        session = await self.get_session_by_jti(jti)
        if session:
            await self.revoke_session(session)
            return True
        return False

    async def refresh_tokens(self, refresh_jti: str) -> Optional[tuple[Session, User]]:
        """
        Refresh access token using refresh token.

        Args:
            refresh_jti: JWT ID claim from refresh token

        Returns:
            Tuple of (new Session, User) or None if refresh fails
        """
        session = await self.get_session_by_refresh_jti(refresh_jti)
        if not session:
            return None

        user = await self.get_user_by_id(session.user_id)
        if not user or not user.is_active:
            return None

        # Revoke old session and create new one
        await self.revoke_session(session)

        new_session = await self.create_session(
            user.id,
            session.organization_id
        )

        return new_session, user

    # ============================================================
    # Organization Membership Operations
    # ============================================================

    async def is_organization_member(
        self,
        user_id: UUID,
        organization_id: UUID
    ) -> bool:
        """
        Check if user is a member of an organization.

        Args:
            user_id: UUID of the user
            organization_id: UUID of the organization

        Returns:
            True if user is an active member, False otherwise
        """
        result = await self.db.execute(
            select(Membership).where(
                and_(
                    Membership.user_id == user_id,
                    Membership.organization_id == organization_id,
                    Membership.is_active == True
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_user_organizations(self, user_id: UUID) -> list[Organization]:
        """
        Get all organizations user belongs to.

        Args:
            user_id: UUID of the user

        Returns:
            List of Organization objects with membership info
        """
        result = await self.db.execute(
            select(Organization, Membership)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(
                and_(
                    Membership.user_id == user_id,
                    Membership.is_active == True,
                    Organization.is_active == True
                )
            )
        )

        organizations = []
        for org, membership in result.all():
            org.membership_role = membership.role
            organizations.append(org)

        return organizations

    async def switch_organization(
        self,
        user_id: UUID,
        organization_id: UUID,
        current_jti: str
    ) -> Optional[Session]:
        """
        Switch user's active organization context.

        Creates a new session with the selected organization.

        Args:
            user_id: UUID of the user
            organization_id: UUID of organization to switch to
            current_jti: Current session JTI (will be revoked)

        Returns:
            New Session object or None if switch fails
        """
        # Verify membership
        if not await self.is_organization_member(user_id, organization_id):
            return None

        # Revoke current session
        current_session = await self.get_session_by_jti(current_jti)
        if current_session:
            await self.revoke_session(current_session)

        # Create new session with new organization context
        new_session = await self.create_session(user_id, organization_id)

        return new_session

    # ============================================================
    # Utility Methods
    # ============================================================

    def _validate_password(self, password: str) -> None:
        """
        Validate password meets requirements.

        Args:
            password: Password to validate

        Raises:
            ValueError: If password doesn't meet requirements
        """
        min_len = settings.PASSWORD_MIN_LENGTH
        max_len = settings.PASSWORD_MAX_LENGTH

        if len(password) < min_len:
            raise ValueError(
                f"Password must be at least {min_len} characters"
            )

        if len(password) > max_len:
            raise ValueError(
                f"Password must be at most {max_len} characters"
            )

    async def get_or_create_default_organization(
        self,
        user: User
    ) -> Organization:
        """
        Get or create a default organization for a user.

        Creates a personal organization named after the user if none exists.

        Args:
            user: User object

        Returns:
            Organization object
        """
        # Check if user already has an organization
        orgs = await self.get_user_organizations(user.id)
        if orgs:
            return orgs[0]

        # Create default organization
        slug = self._generate_organization_slug(user.full_name)

        organization = Organization(
            name=f"{user.full_name}'s Organization",
            slug=slug
        )

        self.db.add(organization)
        await self.db.flush()  # Get the ID without committing

        # Create owner membership
        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            role=UserRole.OWNER.value
        )
        self.db.add(membership)
        await self.db.commit()
        await self.db.refresh(organization)

        return organization

    def _generate_organization_slug(self, name: str) -> str:
        """
        Generate a URL-friendly slug from organization name.

        Args:
            name: Organization name

        Returns:
            URL-safe slug string
        """
        import re
        base = re.sub(r'[^\w\s-]', '', name).strip().lower()
        base = re.sub(r'[-\s]+', '-', base)
        return f"{base}-{uuid4().hex[:8]}"
