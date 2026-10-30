"""inbox: единый жёлоб для входящего и разбор по шести исходам (P-002)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-30 23:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'c9d0e1f2a3b4'
down_revision: str | None = 'b8c9d0e1f2a3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'inbox_items',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        # пусто — личный пункт: проект ещё не выбран
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('url', sa.String(length=1000), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.String(length=200), nullable=True),
        sa.Column('for_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='NEW'),
        sa.Column('outcome', sa.String(length=20), nullable=True),
        sa.Column('outcome_note', sa.Text(), nullable=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reference_url', sa.String(length=1000), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # повтор того же внешнего id не кладёт второй пункт
        sa.UniqueConstraint('project_id', 'source', 'external_id', name='uq_inbox_external'),
    )
    op.create_index('ix_inbox_items_workspace_id', 'inbox_items', ['workspace_id'])
    op.create_index('ix_inbox_items_project_id', 'inbox_items', ['project_id'])
    op.create_index('ix_inbox_items_for_user_id', 'inbox_items', ['for_user_id'])
    op.create_index('ix_inbox_items_created_by_id', 'inbox_items', ['created_by_id'])
    op.create_index('ix_inbox_items_status', 'inbox_items', ['status'])
    op.create_index('ix_inbox_items_outcome', 'inbox_items', ['outcome'])
    op.create_index('ix_inbox_items_task_id', 'inbox_items', ['task_id'])
    # очередь разбора: «что лежит неразобранным» — самый частый запрос
    op.create_index('ix_inbox_items_queue', 'inbox_items', ['workspace_id', 'status', 'created_at'])


def downgrade() -> None:
    op.drop_table('inbox_items')
