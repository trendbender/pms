"""Срабатывание напоминаний: кому, куда и когда следующее.

Это то место, где раньше был bash на чужом сервере. Логика вся здесь:

1. берём напоминания, которым пора, с блокировкой строки (`SKIP LOCKED`) —
   два воркера не отправят одно и то же дважды;
2. **сначала проверяем, нужно ли ещё напоминать**: задача в категории DONE,
   вышел срок, исчерпан лимит — напоминание закрывается само и больше никого
   не трогает. Это и есть «напоминай, пока не закроем», записанное полем;
3. если нужно — кладём сообщение в исходящую очередь (внешний канал) и
   уведомление внутри PMS, пишем строку в журнал задачи;
4. считаем следующий момент. Не нашли — напоминание отработало.

Эскалация срабатывает один раз, на N-м напоминании: человек, которому
напоминают третий раз подряд, обычно не «забыл», а не может или не хочет, и
это уже вопрос к тому, кто поставил задачу.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.comment import Comment
from app.models.delivery import OutboxMessage, ProjectChannel
from app.models.enums import ReminderStatus, StatusCategory
from app.models.reminder import Reminder
from app.models.task import Task, TaskStatus
from app.modules.audit.service import record_activity
from app.modules.notifications.service import notify
from app.modules.reminders.schedule import next_fire_at

# Сколько напоминаний берём за один тик: остальные подождут следующей минуты.
BATCH = 50


def anchor_date_for(reminder: Reminder, task: Task) -> date | None:
    """Дата, посчитанная от срока задачи, если напоминание к нему привязано."""
    if reminder.due_offset_days is None or task.due_at is None:
        return None
    local_due = task.due_at.astimezone(ZoneInfo(reminder.timezone)).date()
    return local_due + timedelta(days=reminder.due_offset_days)


def plan_next(reminder: Reminder, task: Task, *, after: datetime | None) -> bool:
    """Поставить следующий момент. False — расписание исчерпано."""
    moment = next_fire_at(
        schedule=reminder.schedule,
        at_time=reminder.at_time,
        timezone=reminder.timezone,
        start_on=reminder.start_on,
        weekday=reminder.weekday,
        until_on=reminder.until_on,
        after=after,
        anchor_date=anchor_date_for(reminder, task),
    )
    reminder.next_fire_at = moment
    return moment is not None


def stop(reminder: Reminder, reason: str, *, status: str = ReminderStatus.COMPLETED) -> None:
    reminder.status = status
    reminder.stop_reason = reason
    reminder.next_fire_at = None
    reminder.stopped_at = datetime.now(UTC)


def task_link(task: Task) -> str:
    return f"{settings.public_url.rstrip('/')}/t/{task.key.lower()}"


def build_body(reminder: Reminder, task: Task) -> str:
    """Текст для внешнего канала: упоминание, суть, ссылка на задачу."""
    head = f"{reminder.mention} " if reminder.mention else ""
    text = reminder.message or f"Напоминание по {task.key}: {task.title}"
    return f"{head}{text}\n{task_link(task)}"


async def _status_category(db: AsyncSession, status_id: UUID) -> str | None:
    return await db.scalar(select(TaskStatus.category).where(TaskStatus.id == status_id))


async def _channel(db: AsyncSession, channel_id: UUID | None) -> ProjectChannel | None:
    if channel_id is None:
        return None
    return await db.scalar(select(ProjectChannel).where(ProjectChannel.id == channel_id))


def _stop_reason(
    reminder: Reminder, task: Task | None, category: str | None, today: date
) -> str | None:
    """Почему напоминать больше не нужно. None — нужно."""
    if task is None or task.deleted_at is not None:
        return "задача удалена"
    if reminder.stop_on_done and category == StatusCategory.DONE:
        return "задача закрыта"
    if reminder.until_on and today > reminder.until_on:
        return "вышел срок напоминаний"
    if reminder.max_fires is not None and reminder.fire_count >= reminder.max_fires:
        return "исчерпан лимит напоминаний"
    return None


def plan_initial(reminder: Reminder, task: Task, *, now: datetime) -> bool:
    """Первый момент при заведении. False — напоминать уже не о чем (момент прошёл)."""
    return plan_next(reminder, task, after=now)


async def reschedule_for_task(db: AsyncSession, task: Task, *, now: datetime) -> int:
    """Пересчитать напоминания, привязанные к сроку задачи: срок двинули — едут и они.

    Напоминания без якоря (`due_offset_days` пуст) не трогаем: их расписание
    задано датой начала и к сроку отношения не имеет.
    """
    rows = await db.scalars(
        select(Reminder).where(
            Reminder.task_id == task.id,
            Reminder.status == ReminderStatus.ACTIVE,
            Reminder.due_offset_days.is_not(None),
        )
    )
    moved = 0
    for reminder in rows.all():
        if not plan_next(reminder, task, after=now):
            stop(reminder, "срок задачи ушёл в прошлое")
        moved += 1
    return moved


async def fire_due(db: AsyncSession, now: datetime, *, limit: int = BATCH) -> int:
    """Отработать все напоминания, которым пора. Возвращает число отправленных."""
    rows = await db.scalars(
        select(Reminder)
        .where(
            Reminder.status == ReminderStatus.ACTIVE,
            Reminder.next_fire_at.is_not(None),
            Reminder.next_fire_at <= now,
        )
        .order_by(Reminder.next_fire_at)
        .limit(limit)
        .with_for_update(skip_locked=True, of=Reminder)
    )

    fired = 0
    for reminder in rows.all():
        task = await db.get(Task, reminder.task_id)
        category = await _status_category(db, task.status_id) if task else None
        today = now.astimezone(ZoneInfo(reminder.timezone)).date()

        reason = _stop_reason(reminder, task, category, today)
        if reason is not None:
            stop(reminder, reason)
            if task is not None:
                await record_activity(
                    db,
                    workspace_id=reminder.workspace_id,
                    task_id=task.id,
                    actor_id=None,
                    action="reminder.stopped",
                    data={"reason": reason, "fires": reminder.fire_count},
                )
            continue

        scheduled_for = reminder.next_fire_at
        body = build_body(reminder, task)

        channel = await _channel(db, reminder.channel_id)
        if channel is not None and channel.enabled:
            db.add(
                OutboxMessage(
                    workspace_id=reminder.workspace_id,
                    project_id=reminder.project_id,
                    channel_id=channel.id,
                    reminder_id=reminder.id,
                    task_id=task.id,
                    kind="reminder",
                    address=channel.address,
                    thread_id=channel.thread_id,
                    body=body,
                    scheduled_for=scheduled_for,
                )
            )

        await notify(
            db,
            workspace_id=reminder.workspace_id,
            user_id=reminder.notify_user_id or task.assignee_id,
            actor_id=None,
            kind="reminder",
            title=f"Напоминание по {task.key}",
            body=reminder.message or task.title,
            task_id=task.id,
            payload={"reminder_id": str(reminder.id)},
        )

        if reminder.comment_on_task:
            db.add(
                Comment(
                    workspace_id=reminder.workspace_id,
                    task_id=task.id,
                    author_id=reminder.created_by_id,
                    body=body,
                )
            )

        reminder.fire_count += 1
        reminder.last_fire_at = scheduled_for
        fired += 1

        await record_activity(
            db,
            workspace_id=reminder.workspace_id,
            task_id=task.id,
            actor_id=None,
            action="reminder.fired",
            data={"fire": reminder.fire_count, "channel": channel.name if channel else None},
        )

        if (
            reminder.escalate_after_fires is not None
            and reminder.escalate_to_id is not None
            and reminder.fire_count == reminder.escalate_after_fires
        ):
            await notify(
                db,
                workspace_id=reminder.workspace_id,
                user_id=reminder.escalate_to_id,
                actor_id=None,
                kind="reminder.escalated",
                title=f"{task.key}: напомнили {reminder.fire_count} раз, ответа нет",
                body=task.title,
                task_id=task.id,
                payload={"reminder_id": str(reminder.id)},
            )

        if not plan_next(reminder, task, after=scheduled_for):
            stop(reminder, "расписание отработано")

    return fired
