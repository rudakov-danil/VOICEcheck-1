"""
Add username and organization access code.

Revision ID: 004_username_org_code
Revises: 003_add_auth_system
Create Date: 2026-02-19 23:30:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_username_org_code'
down_revision = '003_add_auth_system'
branch_labels = None
depends_on = None


def upgrade():
    """Add username and organization access_code fields."""

    # Add username column to users (nullable first)
    op.add_column('users',
        sa.Column('username', sa.String(100), nullable=True)
    )

    # Make email nullable
    op.alter_column('users',
        'email',
        existing_type=sa.String(255),
        nullable=True
    )

    # Create unique index on username (only non-null values)
    # Using partial index for PostgreSQL
    op.execute("""
        CREATE UNIQUE INDEX ix_users_username 
        ON users (username) 
        WHERE username IS NOT NULL
    """)

    # Add access_code column to organizations (nullable first)
    op.add_column('organizations',
        sa.Column('access_code', sa.String(20), nullable=True)
    )

    # Generate access codes for existing organizations
    import hashlib
    import uuid

    # Get all organizations without access code
    orgs = op.get_bind().execute(
        sa.text("SELECT id, slug FROM organizations WHERE access_code IS NULL")
    ).fetchall()
    
    for org_id, slug in orgs:
        # Generate unique 6-character code
        while True:
            code = ''.join(c for c in hashlib.md5(f"{slug}{org_id}{uuid.uuid4()}".encode()).hexdigest()[:6].upper() if c.isalnum())
            if len(code) == 6:
                # Check uniqueness
                existing = op.get_bind().execute(
                    sa.text("SELECT id FROM organizations WHERE access_code = :code"),
                    {"code": code}
                ).fetchone()
                if not existing:
                    op.get_bind().execute(
                        sa.text("UPDATE organizations SET access_code = :code WHERE id = :id"),
                        {"code": code, "id": str(org_id)}
                    )
                    break

    # Now make column non-nullable
    op.alter_column('organizations',
        'access_code',
        nullable=False
    )

    # Create unique index
    op.create_index('ix_organizations_access_code', 'organizations', ['access_code'], unique=True)


def downgrade():
    """Remove username and organization access_code fields."""

    # Remove access_code from organizations
    op.drop_index('ix_organizations_access_code', table_name='organizations')
    op.drop_column('organizations', 'access_code')

    # Remove username from users
    op.execute("DROP INDEX IF EXISTS ix_users_username")
    op.drop_column('users', 'username')

    # Make email not nullable again
    op.alter_column('users',
        'email',
        existing_type=sa.String(255),
        nullable=False
    )
