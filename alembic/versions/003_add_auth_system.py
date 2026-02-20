"""Add authentication and organization system

Revision ID: 003_add_auth_system
Revises: 002_add_seller_name_and_summary
Create Date: 2025-02-19 00:00:00.000000

This migration adds:
- users table: User accounts with email/password authentication
- organizations table: Organization/company entities
- memberships table: User-organization relationships with roles
- sessions table: JWT session tracking for logout functionality
- Extensions to dialogs table: owner_type, owner_id, created_by for multi-tenancy

Key design decisions:
- No invitations table (users created directly by org owners)
- Passwords stored as bcrypt hashes
- Sessions track JWT tokens for revocation
- Dialogs can be owned by organizations or users (polymorphic)
- All new fields are nullable for backward compatibility
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid


# revision identifiers, used by Alembic.
revision = '003_add_auth_system'
down_revision = '002_add_seller_name_and_summary'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create extension for UUID generation (if not exists)
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ============================================================
    # Create users table
    # ============================================================
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()')),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # ============================================================
    # Create organizations table
    # ============================================================
    op.create_table(
        'organizations',
        sa.Column('id', UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_organizations_id', 'organizations', ['id'])
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)

    # ============================================================
    # Create memberships table (user-organization junction)
    # ============================================================
    op.create_table(
        'memberships',
        sa.Column('id', UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default='member'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'organization_id', name='uq_user_organization'),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name='ck_memberships_valid_role'
        )
    )
    op.create_index('ix_memberships_id', 'memberships', ['id'])
    op.create_index('ix_memberships_user_id', 'memberships', ['user_id'])
    op.create_index('ix_memberships_organization_id', 'memberships', ['organization_id'])

    # ============================================================
    # Create sessions table (JWT token tracking)
    # ============================================================
    op.create_table(
        'sessions',
        sa.Column('id', UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('token_jti', sa.String(255), nullable=False),
        sa.Column('refresh_token_jti', sa.String(255), nullable=True),
        sa.Column('organization_id', UUID(as_uuid=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('token_jti', name='uq_sessions_token_jti'),
        sa.UniqueConstraint('refresh_token_jti', name='uq_sessions_refresh_token_jti')
    )
    op.create_index('ix_sessions_id', 'sessions', ['id'])
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])
    op.create_index('ix_sessions_token_jti', 'sessions', ['token_jti'])
    op.create_index('ix_sessions_organization_id', 'sessions', ['organization_id'])

    # ============================================================
    # Extend dialogs table for organization ownership
    # ============================================================
    # Add new columns for multi-tenancy support (all nullable for backward compatibility)
    op.add_column('dialogs', sa.Column('owner_type', sa.String(50), nullable=True))
    op.add_column('dialogs', sa.Column('owner_id', UUID(as_uuid=True), nullable=True))
    op.add_column('dialogs', sa.Column('created_by', UUID(as_uuid=True), nullable=True))

    # Add indexes for the new columns
    op.create_index('ix_dialogs_owner_type', 'dialogs', ['owner_type'])
    op.create_index('ix_dialogs_owner_id', 'dialogs', ['owner_id'])
    op.create_index('ix_dialogs_created_by', 'dialogs', ['created_by'])

    # Add check constraint for valid owner_type values
    op.execute("""
        ALTER TABLE dialogs
        ADD CONSTRAINT ck_dialogs_owner_type
        CHECK (owner_type IS NULL OR owner_type IN ('organization', 'user'))
    """)


def downgrade() -> None:
    # ============================================================
    # Remove dialogs extensions
    # ============================================================
    op.drop_index('ix_dialogs_created_by', table_name='dialogs')
    op.drop_index('ix_dialogs_owner_id', table_name='dialogs')
    op.drop_index('ix_dialogs_owner_type', table_name='dialogs')
    op.execute("ALTER TABLE dialogs DROP CONSTRAINT IF EXISTS ck_dialogs_owner_type")
    op.drop_column('dialogs', 'created_by')
    op.drop_column('dialogs', 'owner_id')
    op.drop_column('dialogs', 'owner_type')

    # ============================================================
    # Drop sessions table
    # ============================================================
    op.drop_index('ix_sessions_organization_id', table_name='sessions')
    op.drop_index('ix_sessions_token_jti', table_name='sessions')
    op.drop_index('ix_sessions_user_id', table_name='sessions')
    op.drop_index('ix_sessions_id', table_name='sessions')
    op.drop_table('sessions')

    # ============================================================
    # Drop memberships table
    # ============================================================
    op.drop_index('ix_memberships_organization_id', table_name='memberships')
    op.drop_index('ix_memberships_user_id', table_name='memberships')
    op.drop_index('ix_memberships_id', table_name='memberships')
    op.drop_table('memberships')

    # ============================================================
    # Drop organizations table
    # ============================================================
    op.drop_index('ix_organizations_slug', table_name='organizations')
    op.drop_index('ix_organizations_id', table_name='organizations')
    op.drop_table('organizations')

    # ============================================================
    # Drop users table
    # ============================================================
    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_id', table_name='users')
    op.drop_table('users')
