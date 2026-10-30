"""reminders: напоминания по задачам, каналы проекта и исходящая очередь

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-30 20:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: str | None = 'a7b8c9d0e1f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'project_channels',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='TELEGRAM'),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('address', sa.String(length=200), nullable=False),
        sa.Column('thread_id', sa.String(length=50), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
        sa.UniqueConstraint('project_id', 'kind', 'address', 'thread_id', name='uq_channel_per_project'),
    )
    op.create_index('ix_project_channels_workspace_id', 'project_channels', ['workspace_id'])
    op.create_index('ix_project_channels_project_id', 'project_channels', ['project_id'])

    op.create_table(
        'reminders',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schedule', sa.String(length=20), nullable=False, server_default='ONCE'),
        sa.Column('at_time', sa.Time(timezone=False), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='Europe/Moscow'),
        sa.Column('weekday', sa.Integer(), nullable=True),
        sa.Column('start_on', sa.Date(), nullable=False),
        sa.Column('due_offset_days', sa.Integer(), nullable=True),
        sa.Column('until_on', sa.Date(), nullable=True),
        sa.Column('max_fires', sa.Integer(), nullable=True),
        sa.Column('stop_on_done', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('escalate_after_fires', sa.Integer(), nullable=True),
        sa.Column('escalate_to_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('channel_id', sa.Uuid(), sa.ForeignKey('project_channels.id', ondelete='SET NULL'), nullable=True),
        sa.Column('notify_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('mention', sa.String(length=100), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('comment_on_task', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ACTIVE'),
        sa.Column('next_fire_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_fire_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fire_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('stopped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stop_reason', sa.String(length=200), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        *_ts(),
    )
    op.create_index('ix_reminders_workspace_id', 'reminders', ['workspace_id'])
    op.create_index('ix_reminders_project_id', 'reminders', ['project_id'])
    op.create_index('ix_reminders_task_id', 'reminders', ['task_id'])
    op.create_index('ix_reminders_status', 'reminders', ['status'])
    # Выборка воркера: что пора отправлять.
    op.create_index('ix_reminders_next_fire_at', 'reminders', ['next_fire_at'])

    op.create_table(
        'outbox_messages',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('channel_id', sa.Uuid(), sa.ForeignKey('project_channels.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reminder_id', sa.Uuid(), sa.ForeignKey('reminders.id', ondelete='SET NULL'), nullable=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('kind', sa.String(length=50), nullable=False, server_default='reminder'),
        sa.Column('address', sa.String(length=200), nullable=False),
        sa.Column('thread_id', sa.String(length=50), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        *_ts(),
        sa.UniqueConstraint('reminder_id', 'scheduled_for', name='uq_outbox_reminder_slot'),
    )
    op.create_index('ix_outbox_messages_workspace_id', 'outbox_messages', ['workspace_id'])
    op.create_index('ix_outbox_messages_project_id', 'outbox_messages', ['project_id'])
    op.create_index('ix_outbox_messages_reminder_id', 'outbox_messages', ['reminder_id'])
    op.create_index('ix_outbox_messages_task_id', 'outbox_messages', ['task_id'])
    op.create_index('ix_outbox_messages_status', 'outbox_messages', ['status'])


def downgrade() -> None:
    op.drop_table('outbox_messages')
    op.drop_table('reminders')
    op.drop_table('project_channels')
