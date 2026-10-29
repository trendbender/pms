"""decisions: копия реестра решений из вики (страница /d/, вкладка проекта)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-21 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = 'd4e5f6a7b8c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'decisions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True),
        sa.Column('registry', sa.String(length=64), nullable=False),
        sa.Column('ref', sa.String(length=20), nullable=False),
        sa.Column('area', sa.String(length=40), nullable=True),
        sa.Column('area_title', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('decision', sa.Text(), nullable=True),
        sa.Column('decided_by', sa.String(length=200), nullable=True),
        sa.Column('decided_on', sa.String(length=20), nullable=True),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('applies', sa.Text(), nullable=True),
        sa.Column('supersedes', sa.String(length=20), nullable=True),
        sa.Column('superseded_by', sa.String(length=20), nullable=True),
        sa.Column('keys', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('aliases', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('task_keys', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('workspace_id', 'registry', 'ref', name='uq_decision_ref_per_registry'),
    )
    op.create_index('ix_decisions_workspace_id', 'decisions', ['workspace_id'])
    op.create_index('ix_decisions_project_id', 'decisions', ['project_id'])
    op.create_index('ix_decisions_registry', 'decisions', ['registry'])
    op.create_index('ix_decisions_task_keys', 'decisions', ['task_keys'], postgresql_using='gin')


def downgrade() -> None:
    op.drop_table('decisions')
