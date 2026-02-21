"""
Add departments table and department_id to memberships.

Revision ID: 005_add_departments
Revises: 004_username_org_code
Create Date: 2026-02-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005_add_departments'
down_revision = '004_username_org_code'
branch_labels = None
depends_on = None


def upgrade():
    """Add departments table and department_id FK to memberships."""
    op.create_table(
        'departments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('head_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column('memberships',
        sa.Column('department_id', postgresql.UUID(as_uuid=True), nullable=True)
    )

    op.create_foreign_key(
        'fk_memberships_department_id',
        'memberships', 'departments',
        ['department_id'], ['id'],
        ondelete='SET NULL'
    )

    op.create_index('ix_memberships_department_id', 'memberships', ['department_id'])


def downgrade():
    """Remove departments table and department_id from memberships."""
    op.drop_index('ix_memberships_department_id', table_name='memberships')
    op.drop_constraint('fk_memberships_department_id', 'memberships', type_='foreignkey')
    op.drop_column('memberships', 'department_id')
    op.drop_table('departments')
