"""Add responsible column to companies table.

Revision ID: 007_add_company_responsible
Revises: 006_add_companies
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '007_add_company_responsible'
down_revision = '006_add_companies'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'companies' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('companies')]
        if 'responsible' not in existing_cols:
            op.add_column('companies', sa.Column('responsible', sa.String(255), nullable=True,
                                                  comment='Responsible seller name'))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'companies' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('companies')]
        if 'responsible' in existing_cols:
            op.drop_column('companies', 'responsible')
