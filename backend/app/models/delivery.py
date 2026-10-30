"""Куда проект пишет наружу и что уже ушло.

Разделение ответственности из решения T-003: PMS решает всё (когда, кому, о чём
и нужно ли ещё), складывает готовое сообщение в `outbox_messages`, а отправкой
занимается тупой релей на стороне бота. Релей не знает ни про расписания, ни про
статусы задач — сносишь его, и напоминания остаются живы, просто копится очередь.

`project_channels` — реестр адресов, куда проекту разрешено писать. Он нужен не
для удобства, а чтобы ни агент, ни человек не могли отправить сообщение в
произвольный чат: напоминание ссылается на канал проекта, а не на chat_id.

`outbox_messages` — одновременно очередь и журнал (строки не удаляются). Отсюда
же считается «сколько раз напомнили»: отдельной таблицы отправок нет, чтобы два
списка одного и того же не разъехались.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class ProjectChannel(Base, TimestampMixin):
    __tablename__ = "project_channels"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "kind", "address", "thread_id", name="uq_channel_per_project"
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # TELEGRAM (app.models.enums.ChannelKind); почта появится, когда будет SMTP.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="TELEGRAM")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Адрес в терминах канала: для Telegram — chat_id («-4853904340»).
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    # Топик внутри чата, если он есть.
    thread_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class OutboxMessage(Base, TimestampMixin):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        # Идемпотентность: повторный тик воркера на тот же момент не создаст
        # второе сообщение. У дайджестов reminder_id пуст, и PostgreSQL считает
        # NULL-ы разными — их это ограничение не трогает.
        UniqueConstraint("reminder_id", "scheduled_for", name="uq_outbox_reminder_slot"),
    )

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_channels.id", ondelete="SET NULL"), nullable=True
    )
    reminder_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reminders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # reminder / digest / alert — кем порождено сообщение.
    kind: Mapped[str] = mapped_column(String(50), nullable=False, default="reminder")
    # Копия адреса на момент постановки в очередь: канал могли выключить или снести.
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # На какой момент сообщение было запланировано (не когда поставлено в очередь).
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # PENDING / SENT / FAILED / CANCELLED (app.models.enums.OutboxStatus)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
