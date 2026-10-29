"""roadmaps: роадмап проекта, его метрики и волны (инициативы)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-29 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a7b8c9d0e1f2'
down_revision: str | None = 'f6a7b8c9d0e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'roadmaps',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='DRAFT'),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('scope_note', sa.Text(), nullable=True),
        sa.Column('agreed_on', sa.Date(), nullable=True),
        sa.Column('decision_ref', sa.String(length=40), nullable=True),
        sa.Column('plan_url', sa.String(length=1000), nullable=True),
        sa.Column('report_url', sa.String(length=1000), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index('ix_roadmaps_workspace_id', 'roadmaps', ['workspace_id'])
    op.create_index('ix_roadmaps_project_id', 'roadmaps', ['project_id'])
    op.create_index('ix_roadmaps_period_start', 'roadmaps', ['period_start'])

    op.create_table(
        'roadmap_metrics',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('roadmap_id', sa.Uuid(), sa.ForeignKey('roadmaps.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('baseline', sa.Text(), nullable=True),
        sa.Column('baseline_on', sa.Date(), nullable=True),
        sa.Column('target', sa.Text(), nullable=True),
        sa.Column('current', sa.Text(), nullable=True),
        sa.Column('measured_on', sa.Date(), nullable=True),
        sa.Column('source', sa.String(length=255), nullable=True),
        sa.Column('reached_on', sa.Date(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
    )
    op.create_index('ix_roadmap_metrics_workspace_id', 'roadmap_metrics', ['workspace_id'])
    op.create_index('ix_roadmap_metrics_roadmap_id', 'roadmap_metrics', ['roadmap_id'])

    # волна роадмапа это инициатива: прогресс остаётся на задачах инициативы
    op.add_column('initiatives', sa.Column('roadmap_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_initiatives_roadmap_id', 'initiatives', 'roadmaps', ['roadmap_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_initiatives_roadmap_id', 'initiatives', ['roadmap_id'])


def downgrade() -> None:
    op.drop_index('ix_initiatives_roadmap_id', table_name='initiatives')
    op.drop_constraint('fk_initiatives_roadmap_id', 'initiatives', type_='foreignkey')
    op.drop_column('initiatives', 'roadmap_id')
    op.drop_table('roadmap_metrics')
    op.drop_table('roadmaps')
