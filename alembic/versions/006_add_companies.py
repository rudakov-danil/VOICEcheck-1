"""
Add companies table, csv_import_mappings table and company_id to dialogs.

Revision ID: 006_add_companies
Revises: 005_add_departments
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = '006_add_companies'
down_revision = '005_add_departments'
branch_labels = None
depends_on = None


def upgrade():
    """Create companies and csv_import_mappings tables; add company_id to dialogs."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # --- companies ---
    if 'companies' not in existing_tables:
        op.create_table(
            'companies',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('owner_type', sa.String(50), nullable=True),
            sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('inn', sa.String(20), nullable=True),
            sa.Column('external_id', sa.String(255), nullable=True),
            sa.Column('contact_person', sa.String(255), nullable=True),
            sa.Column('phone', sa.String(100), nullable=True),
            sa.Column('email', sa.String(255), nullable=True),
            sa.Column('address', sa.Text, nullable=True),
            sa.Column('industry', sa.String(255), nullable=True),
            sa.Column('funnel_stage', sa.String(100), nullable=True),
            sa.Column('custom_fields', postgresql.JSONB, nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        # Indexes for companies
        op.create_index('ix_companies_owner_type', 'companies', ['owner_type'])
        op.create_index('ix_companies_owner_id', 'companies', ['owner_id'])
        op.create_index('ix_companies_created_by', 'companies', ['created_by'])
        op.create_index('ix_companies_name', 'companies', ['name'])
        op.create_index('ix_companies_inn', 'companies', ['inn'])
        op.create_index('ix_companies_external_id', 'companies', ['external_id'])
        op.create_index('ix_companies_created_at', 'companies', ['created_at'])

    # --- csv_import_mappings ---
    if 'csv_import_mappings' not in existing_tables:
        op.create_table(
            'csv_import_mappings',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('owner_type', sa.String(50), nullable=True),
            sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('mapping', postgresql.JSONB, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_csv_import_mappings_owner_type', 'csv_import_mappings', ['owner_type'])
        op.create_index('ix_csv_import_mappings_owner_id', 'csv_import_mappings', ['owner_id'])

    # --- company_id FK in dialogs ---
    existing_cols = [c['name'] for c in inspector.get_columns('dialogs')]
    if 'company_id' not in existing_cols:
        op.add_column('dialogs',
            sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True)
        )
        op.create_foreign_key(
            'fk_dialogs_company_id',
            'dialogs', 'companies',
            ['company_id'], ['id'],
            ondelete='SET NULL'
        )
        op.create_index('ix_dialogs_company_id', 'dialogs', ['company_id'])


def downgrade():
    """Remove companies tables and company_id from dialogs."""
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_cols = [c['name'] for c in inspector.get_columns('dialogs')]
    if 'company_id' in existing_cols:
        op.drop_index('ix_dialogs_company_id', table_name='dialogs')
        op.drop_constraint('fk_dialogs_company_id', 'dialogs', type_='foreignkey')
        op.drop_column('dialogs', 'company_id')

    existing_tables = inspector.get_table_names()
    if 'csv_import_mappings' in existing_tables:
        op.drop_table('csv_import_mappings')
    if 'companies' in existing_tables:
        op.drop_table('companies')
