"""Реестр решений: копия `decisions.yaml` из вики (решение _global:P-022, 21.10.2026).

Источник правды остаётся в вике (утилита `decisions.py`, git-история). PMS только
показывает копию: страница решения `/d/<КОД>-<ID>`, вкладка «Решения» в проекте,
связь с задачами. Таблица целиком перезаписывается синком реестра, руками её не правят.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class Decision(Base):
    """Одна запись реестра. `registry` это имя реестра в вике (`skolkoskolko`,
    `_global`), `ref` его номер внутри реестра (`P-030`). У `_global` нет проекта."""

    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "registry", "ref", name="uq_decision_ref_per_registry"),
        Index("ix_decisions_task_keys", "task_keys", postgresql_using="gin"),
    )

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    registry: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String(20), nullable=False)
    area: Mapped[str | None] = mapped_column(String(40), nullable=True)
    area_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # accepted / open / superseded / rejected, как в decisions.yaml
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_on: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    applies: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes: Mapped[str | None] = mapped_column(String(20), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # ключи задач PMS (`SSK-203`): из поля `tasks` записи и из ссылок в `source`
    task_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
