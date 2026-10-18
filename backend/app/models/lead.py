"""Лиды проекта: этапы воронки, свои поля, лид, журнал и ключи приёма.

Лид это не задача: у него своя воронка (этапы на проект), свои поля и контакт.
Модуль включается флагом `projects.leads_enabled`, остальные проекты его не видят.
Работа по лиду (аудит, КП) остаётся обычной задачей и связывается через `task_id`.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class LeadStage(Base, TimestampMixin):
    """Этап воронки. Категория (OPEN/WON/LOST) нужна логике и статистике,
    чтобы не зависеть от названий, которые владелец переименует как угодно."""

    __tablename__ = "lead_stages"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_lead_stage_per_project"),)

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)


class LeadField(Base, TimestampMixin):
    """Своё поле лида на проект. Значения лежат в `leads.data` по `key`."""

    __tablename__ = "lead_fields"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_lead_field_per_project"),)

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Персональные данные: по этому флагу поле обезличивается по сроку хранения
    # или по запросу субъекта. На права не влияет (решение 18.10.2026).
    is_pii: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_lead_key_per_workspace"),
        # повторный вебхук с тем же внешним id не создаёт дубль (NULL не сравнивается)
        UniqueConstraint("project_id", "source", "external_id", name="uq_lead_external"),
        Index("ix_leads_project_received", "project_id", "received_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("lead_stages.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")

    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    duplicate_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadEvent(Base, TimestampMixin):
    """Журнал лида, только дописывается: создание, смена этапа, правки, комментарии,
    повторный приём. Комментарий это тоже событие (`comment`), отдельной таблицы нет."""

    __tablename__ = "lead_events"

    # clock_timestamp, а не now(): несколько событий одного запроса (повтор +
    # смена этапа) должны получить разное время, иначе журнал перемешается
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # если событие пришло через ключ приёма, а не от пользователя
    token_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lead_ingest_tokens.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class LeadIngestToken(Base, TimestampMixin):
    """Ключ приёма лидов в проект (вебхуки форм, адаптеры площадок).
    Значение показывается один раз при создании, в базе только sha256."""

    __tablename__ = "lead_ingest_tokens"

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # первые символы ключа, чтобы в настройках различать ключи без раскрытия значения
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
