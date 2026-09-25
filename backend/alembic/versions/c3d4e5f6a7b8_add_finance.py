"""finance: contracts + payments, initiative due_date (вехи с датой)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-25 13:40:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('initiatives', sa.Column('due_date', sa.Date(), nullable=True))
    op.create_index('ix_initiatives_due_date', 'initiatives', ['due_date'])

    op.create_table(
        'contracts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='FIXED'),
        sa.Column('amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('rate', sa.Numeric(12, 2), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='RUB'),
        sa.Column('signed_at', sa.Date(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('doc_url', sa.String(length=1000), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_contracts_workspace_id', 'contracts', ['workspace_id'])
    op.create_index('ix_contracts_project_id', 'contracts', ['project_id'])

    op.create_table(
        'payments',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('contract_id', sa.Uuid(), nullable=True),
        sa.Column('initiative_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='MILESTONE'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='EXPECTED'),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='RUB'),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('invoiced_at', sa.Date(), nullable=True),
        sa.Column('paid_at', sa.Date(), nullable=True),
        sa.Column('invoice_no', sa.String(length=50), nullable=True),
        sa.Column('act_no', sa.String(length=50), nullable=True),
        sa.Column('doc_url', sa.String(length=1000), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contract_id'], ['contracts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['initiative_id'], ['initiatives.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_payments_workspace_id', 'payments', ['workspace_id'])
    op.create_index('ix_payments_project_id', 'payments', ['project_id'])
    op.create_index('ix_payments_contract_id', 'payments', ['contract_id'])
    op.create_index('ix_payments_initiative_id', 'payments', ['initiative_id'])
    op.create_index('ix_payments_status', 'payments', ['status'])
    op.create_index('ix_payments_due_date', 'payments', ['due_date'])


def downgrade() -> None:
    op.drop_table('payments')
    op.drop_table('contracts')
    op.drop_index('ix_initiatives_due_date', table_name='initiatives')
    op.drop_column('initiatives', 'due_date')
