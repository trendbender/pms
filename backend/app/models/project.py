from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_project_code_per_workspace"),
    )

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # short task-key prefix, e.g. "SEO", "UBO" — unique within workspace
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    health: Mapped[str] = mapped_column(String(20), nullable=False, default="ON_TRACK")

    # optional portfolio grouping label (e.g. "Клиентские" / "Свои") — free text
    # so the owner can regroup without a schema change
    group_name: Mapped[str | None] = mapped_column(String(60), nullable=True)

    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # WIP limit for IN_PROGRESS (soft limit — warns, does not block in MVP)
    wip_limit: Mapped[int | None] = mapped_column(nullable=True)

    # per-project monotonic counter for task numbers (SEO-1, SEO-2, ...)
    task_counter: Mapped[int] = mapped_column(nullable=False, default=0)

    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectMember(Base, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[UUID] = uuid_pk()
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # per-project role: Owner / Manager / Member / Viewer / Guest
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="MEMBER")
