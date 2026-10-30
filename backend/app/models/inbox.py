"""Инбокс проекта: сырьё, которое ещё не задача.

Единый жёлоб для входящего (решение P-002). До этого входов было пять, а
инбокса ни одного: полтора десятка телеграм-чатов, сессии Claude Code, отчёты,
календарь и голова. ИИ, боты и отчёты кладут входящее сюда, а в чат уходит
только то, что требует решения владельца сейчас.

Почему это не задача:

* **задача — это обязательство, пункт инбокса — ещё нет.** Сырьё на доске
  создаёт видимость работы, которой никто не брал: доска перестаёт отвечать на
  вопрос «что в работе». Поэтому инбокс живёт своей таблицей и на доску не
  попадает.
* **у задачи есть следующее конкретное действие, у сырья его нет.** Разбор как
  раз и есть момент, когда «проверить и отправить отчёт» превращается в
  действие. Поэтому исходы, заводящие задачу, требуют своей формулировки, а не
  копируют заголовок пункта.
* **разбор — это шесть исходов, а не редактирование.** `outcome` пишется один
  раз и остаётся: по нему видно, чем кончилось входящее, а не только что его
  убрали с глаз.

Проект необязателен: мысль «из головы» не обязана сразу знать свой проект, и
требовать проект на входе значит возвращать человека к сортировке в тот момент,
когда он хотел просто записать. Пункт без проекта — личный: его видят автор и
адресат, а §7 (нет доступа к проекту — не видно) при этом не ломается.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class InboxItem(Base, TimestampMixin):
    __tablename__ = "inbox_items"
    __table_args__ = (
        # повторный отчёт или вебхук с тем же внешним id не кладёт второй пункт
        # (NULL не сравнивается, поэтому ручные записи ограничение не трогает)
        UniqueConstraint("project_id", "source", "external_id", name="uq_inbox_external"),
        Index("ix_inbox_items_queue", "workspace_id", "status", "created_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Пусто — личный пункт: автор записал, проект ещё не выбран.
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Откуда пришло: ссылка на сообщение в чате, отчёт, страницу.
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # «telegram», «claude-code», «report», «manual» — свободная строка: источники
    # заводятся быстрее, чем меняется схема.
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Кому адресовано. Пусто — инбокс проекта, разбирает любой, кто его видит.
    for_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Кто положил. Агенты ходят под своими аккаунтами (решение P-004), поэтому
    # в журнале видно, чьё это сырьё, без отдельного ключа приёма.
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="NEW", index=True)

    # Чем кончился разбор: один из шести исходов (app.models.enums.InboxOutcome).
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # Что именно сделано: «написал Антону», «положил в вики projects/pms/…».
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Заведённая задача (исходы TASK / DELEGATED / CALENDAR).
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Куда легла справка (исход REFERENCE): страница вики, таблица, документ.
    reference_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
