from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class ActivityLog(Base, TimestampMixin):
    """Per-task activity feed (task.created, status.changed, ...). Immutable."""

    __tablename__ = "activity_logs"

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # {"field": "status", "from": "REVIEW", "to": "CHANGES_REQUIRED"}
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AuditLog(Base, TimestampMixin):
    """Administrative audit trail (user.invited, permission.changed, ...). Immutable."""

    __tablename__ = "audit_logs"

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
