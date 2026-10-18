"""leads: модуль лидов на проекте (этапы, поля, лиды, журнал, ключи приёма)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-18 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'd4e5f6a7b8c9'
down_revision: str | None = 'c3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column('projects', sa.Column('leads_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('projects', sa.Column('lead_counter', sa.Integer(), nullable=False, server_default='0'))

    op.create_table(
        'lead_stages',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=10), nullable=False, server_default='OPEN'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('color', sa.String(length=20), nullable=True),
        *_ts(),
        sa.UniqueConstraint('project_id', 'name', name='uq_lead_stage_per_project'),
    )
    op.create_index('ix_lead_stages_workspace_id', 'lead_stages', ['workspace_id'])
    op.create_index('ix_lead_stages_project_id', 'lead_stages', ['project_id'])

    op.create_table(
        'lead_fields',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False, server_default='text'),
        sa.Column('options', postgresql.JSONB(), nullable=True),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_pii', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        *_ts(),
        sa.UniqueConstraint('project_id', 'key', name='uq_lead_field_per_project'),
    )
    op.create_index('ix_lead_fields_workspace_id', 'lead_fields', ['workspace_id'])
    op.create_index('ix_lead_fields_project_id', 'lead_fields', ['project_id'])

    op.create_table(
        'lead_ingest_tokens',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False, unique=True),
        sa.Column('prefix', sa.String(length=12), nullable=False),
        sa.Column('created_by_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index('ix_lead_ingest_tokens_workspace_id', 'lead_ingest_tokens', ['workspace_id'])
    op.create_index('ix_lead_ingest_tokens_project_id', 'lead_ingest_tokens', ['project_id'])

    op.create_table(
        'leads',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('stage_id', sa.Uuid(), sa.ForeignKey('lead_stages.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False, server_default='manual'),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('external_id', sa.String(length=200), nullable=True),
        sa.Column('contact_name', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='RUB'),
        sa.Column('data', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lost_reason', sa.Text(), nullable=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('duplicate_of_id', sa.Uuid(), sa.ForeignKey('leads.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint('workspace_id', 'key', name='uq_lead_key_per_workspace'),
        sa.UniqueConstraint('project_id', 'source', 'external_id', name='uq_lead_external'),
    )
    op.create_index('ix_leads_workspace_id', 'leads', ['workspace_id'])
    op.create_index('ix_leads_project_id', 'leads', ['project_id'])
    op.create_index('ix_leads_stage_id', 'leads', ['stage_id'])
    op.create_index('ix_leads_owner_id', 'leads', ['owner_id'])
    op.create_index('ix_leads_project_received', 'leads', ['project_id', 'received_at'])

    op.create_table(
        'lead_events',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lead_id', sa.Uuid(), sa.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('token_id', sa.Uuid(), sa.ForeignKey('lead_ingest_tokens.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('data', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_lead_events_workspace_id', 'lead_events', ['workspace_id'])
    op.create_index('ix_lead_events_lead_id', 'lead_events', ['lead_id'])


def downgrade() -> None:
    op.drop_table('lead_events')
    op.drop_table('leads')
    op.drop_table('lead_ingest_tokens')
    op.drop_table('lead_fields')
    op.drop_table('lead_stages')
    op.drop_column('projects', 'lead_counter')
    op.drop_column('projects', 'leads_enabled')
