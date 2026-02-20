"""Add seller_name to dialogs and summary to dialog_analyses

Revision ID: 002_add_seller_name_and_summary
Revises: 001_initial_tables
Create Date: 2026-02-17
"""
from alembic import op
import sqlalchemy as sa


revision = '002_add_seller_name_and_summary'
down_revision = '001_initial_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dialogs', sa.Column('seller_name', sa.String(255), nullable=True))
    op.create_index('ix_dialogs_seller_name', 'dialogs', ['seller_name'])

    op.add_column('dialog_analyses', sa.Column('summary', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('dialog_analyses', 'summary')

    op.drop_index('ix_dialogs_seller_name', table_name='dialogs')
    op.drop_column('dialogs', 'seller_name')
