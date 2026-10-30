"""Напоминание по задаче: расписание, условие остановки и состояние.

Движок, а не скрипт на стороне. До этого напоминания жили строкой в crontab на
чужом сервере: расписание, условие «пока не закроем» и счётчик напоминаний
лежали в bash, а в PMS о них не знали. Здесь всё наоборот — PMS решает, когда
напомнить, кому, нужно ли ещё, и сам останавливается.

Три вещи, которые делают напоминание напоминанием, а не будильником:

* **условие остановки**. `stop_on_done` снимает напоминание, когда задача
  уходит в категорию DONE: формулировка «напоминай, пока не закроем» живёт
  полем, а не договорённостью. Рядом — `until_on` (до даты) и `max_fires`.
* **якорь к сроку**. `due_offset_days` привязывает напоминание к `task.due_at`
  («за два дня до срока»), поэтому перенос срока двигает и напоминание. Без
  якоря расписание считается от `start_on` и переносом срока не задевается.
* **эскалация**. После `escalate_after_fires` безответных напоминаний
  `escalate_to_id` узнаёт, что человек не отвечает. Напоминание, на которое
  никто не реагирует, — это не напоминание, а фон.

Журнала отправок у напоминания своего нет: каждое срабатывание это строка в
`outbox_messages` с `reminder_id`, и «сколько раз напомнили» считается оттуда.
Две таблицы с одним и тем же смыслом расходятся, одна — нет.
"""

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Первая версия напоминает только по задачам (решение F-003). Платежи, лиды
    # и вехи роадмапа получат свою цель, когда механика обкатается на задачах.
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ONCE / DAILY / WEEKDAYS / WEEKLY (app.models.enums.ReminderSchedule)
    schedule: Mapped[str] = mapped_column(String(20), nullable=False, default="ONCE")
    at_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    # 0 = понедельник. Нужен только для WEEKLY.
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # С какого дня напоминаем. При заданном due_offset_days пересчитывается от срока задачи.
    start_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Якорь к сроку: -2 = «за два дня до срока», 0 = «в день срока», +1 = «на следующий день».
    due_offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    until_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    max_fires: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_on_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    escalate_after_fires: Mapped[int | None] = mapped_column(Integer, nullable=True)
    escalate_to_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Внешний канал (чат проекта). Пусто — напоминание только в PMS.
    channel_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_channels.id", ondelete="SET NULL"), nullable=True
    )
    # Кого уведомляем внутри PMS. Пусто — исполнителя задачи на момент отправки.
    notify_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Кого упомянуть в чате: «@vanstallin». Чат и PMS — разные адресные книги.
    mention: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Свой текст вместо собранного из задачи.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Оставлять ли след комментарием в задаче. По умолчанию нет: журнал ведёт
    # outbox, а комментарии от робота заслоняют живое обсуждение.
    comment_on_task: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", index=True)
    next_fire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fire_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # «задача закрыта», «снято Дмитрием», «вышел срок until_on» — видно в карточке.
    stop_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
