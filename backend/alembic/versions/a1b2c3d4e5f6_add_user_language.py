"""add user.language (UI language preference)

Revision ID: a1b2c3d4e5f6
Revises: 68d3939a5281
Create Date: 2026-09-05 17:40:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '68d3939a5281'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'language',
            sa.String(length=8),
            nullable=False,
            server_default='ru',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'language')
