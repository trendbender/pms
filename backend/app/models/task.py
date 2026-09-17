from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class TaskType(Base, TimestampMixin):
    """Configurable task type, scoped to a project (TASK/BUG/FEATURE/...)."""

    __tablename__ = "task_types"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_task_type_per_project"),)

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TaskStatus(Base, TimestampMixin):
    """Configurable status column, scoped to a project. Maps to a StatusCategory."""

    __tablename__ = "task_statuses"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_task_status_per_project"),)

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_task_key_per_workspace"),
        UniqueConstraint("project_id", "number", name="uq_task_number_per_project"),
    )

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "SEO-145"

    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    initiative_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("initiatives.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    type_id: Mapped[UUID] = mapped_column(
        ForeignKey("task_types.id", ondelete="RESTRICT"), nullable=False
    )
    status_id: Mapped[UUID] = mapped_column(
        ForeignKey("task_statuses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")

    assignee_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reporter_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    sprint_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sprints.id", ondelete="SET NULL"), nullable=True, index=True
    )

    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition_of_done: Mapped[str | None] = mapped_column(Text, nullable=True)

    # blocker visibility (Rule 8) — reason surfaced on the card
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    story_points: Mapped[int | None] = mapped_column(Integer, nullable=True)

    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # fractional ordering (LexoRank-like) — avoids reindexing on every move
    position: Mapped[float] = mapped_column(Numeric, nullable=False, default=1000)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
