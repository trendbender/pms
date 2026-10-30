"""API напоминаний, каналов проекта и исходящей очереди.

Права разведены намеренно (решение T-003 и правило «внешнее — отдельно»):
напоминание внутри PMS ставит любой участник проекта, а отправку в чат
проекта открывает только `reminder.external` у управляющего уровня.
Исполнитель не должен уметь написать клиенту от имени проекта.

Очередь (`/outbox/...`) — это интерфейс для релея, а не для людей: он забирает
готовые сообщения и отмечает их отправленными. Поэтому права на неё
workspace-уровня, как у служебного аккаунта бота.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import DbSession
from app.core.deps import (
    get_current_user,
    get_workspace_id,
    require_project_permission,
    require_workspace_permission,
)
from app.models.delivery import OutboxMessage, ProjectChannel
from app.models.enums import OutboxStatus, ReminderStatus
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.projects.service import list_visible_projects
from app.modules.reminders import service
from app.modules.reminders.schemas import (
    ChannelCreate,
    ChannelOut,
    ChannelUpdate,
    OutboxOut,
    ReminderCreate,
    ReminderDetail,
    ReminderOut,
    ReminderUpdate,
    SnoozeRequest,
)

router = APIRouter(tags=["reminders"])

# Сколько раз релей пробует отдать сообщение, прежде чем оно признаётся неудачным.
MAX_ATTEMPTS = 3


async def _load_task(db: AsyncSession, user: User, workspace_id: UUID, task_id: UUID) -> Task:
    task = await db.get(Task, task_id)
    if task is None or task.workspace_id != workspace_id or task.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, task.project_id, Perm.REMINDER_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


async def load_reminder(
    reminder_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> Reminder:
    obj = await db.get(Reminder, reminder_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reminder not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, obj.project_id, Perm.REMINDER_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reminder not found")
    return obj


async def _require(db: AsyncSession, user: User, project_id: UUID, ws: UUID, perm: Perm) -> None:
    if not await perms.has_project_permission(db, user.id, ws, project_id, perm):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")


def _check_timezone(name: str) -> None:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown timezone: {name}") from exc


async def _check_channel(
    db: AsyncSession, user: User, ws: UUID, project_id: UUID, channel_id: UUID | None
) -> None:
    """Канал обязан принадлежать проекту, быть включённым и быть разрешённым роли."""
    if channel_id is None:
        return
    await _require(db, user, project_id, ws, Perm.REMINDER_EXTERNAL)
    channel = await db.get(ProjectChannel, channel_id)
    if channel is None or channel.project_id != project_id or channel.workspace_id != ws:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Channel does not belong to the project")
    if not channel.enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Channel is disabled")


async def _detail(db: AsyncSession, reminder: Reminder) -> ReminderDetail:
    task = await db.get(Task, reminder.task_id)
    log = (
        await db.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.reminder_id == reminder.id)
            .order_by(OutboxMessage.scheduled_for.desc())
            .limit(50)
        )
    ).all()
    out = ReminderDetail.model_validate(reminder)
    out.task_key = task.key if task else None
    out.log = [OutboxOut.model_validate(m) for m in log]
    return out


# --------------------------------------------------------------------------- #
# Напоминания
# --------------------------------------------------------------------------- #


@router.post(
    "/tasks/{task_id}/reminders",
    response_model=ReminderDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_reminder(
    task_id: UUID,
    body: ReminderCreate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> ReminderDetail:
    task = await _load_task(db, user, workspace_id, task_id)
    await _require(db, user, task.project_id, workspace_id, Perm.REMINDER_MANAGE)
    _check_timezone(body.timezone)
    await _check_channel(db, user, workspace_id, task.project_id, body.channel_id)

    now = datetime.now(UTC)
    data = body.model_dump()
    # Без своей даты начала считаем от сегодня: точку отсчёта даст срок задачи.
    data["start_on"] = data["start_on"] or now.astimezone(ZoneInfo(body.timezone)).date()
    reminder = Reminder(
        workspace_id=workspace_id,
        project_id=task.project_id,
        task_id=task.id,
        created_by_id=user.id,
        **data,
    )
    if not service.plan_initial(reminder, task, now=now):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Напоминать не о чем: этот момент уже прошёл",
        )
    db.add(reminder)
    await db.flush()
    return await _detail(db, reminder)


@router.get("/tasks/{task_id}/reminders", response_model=list[ReminderOut])
async def list_task_reminders(
    task_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> list[ReminderOut]:
    task = await _load_task(db, user, workspace_id, task_id)
    rows = await db.scalars(
        select(Reminder)
        .where(Reminder.task_id == task.id)
        .order_by(Reminder.created_at.desc())
    )
    out = []
    for r in rows.all():
        item = ReminderOut.model_validate(r)
        item.task_key = task.key
        out.append(item)
    return out


@router.get("/reminders", response_model=list[ReminderOut])
async def list_reminders(
    project_id: UUID | None = None,
    active_only: bool = True,
    limit: int = 200,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> list[ReminderOut]:
    """Напоминания по видимым проектам: что сейчас стоит и на когда."""
    visible = {p.id for p in await list_visible_projects(db, user.id, workspace_id)}
    if project_id is not None:
        visible &= {project_id}
    if not visible:
        return []
    query = (
        select(Reminder, Task.key)
        .join(Task, Task.id == Reminder.task_id)
        .where(Reminder.project_id.in_(visible))
        .order_by(Reminder.next_fire_at.is_(None), Reminder.next_fire_at)
        .limit(min(limit, 500))
    )
    if active_only:
        query = query.where(Reminder.status == ReminderStatus.ACTIVE)
    out = []
    for reminder, key in (await db.execute(query)).all():
        item = ReminderOut.model_validate(reminder)
        item.task_key = key
        out.append(item)
    return out


@router.get("/reminders/{reminder_id}", response_model=ReminderDetail)
async def get_reminder(
    reminder: Reminder = Depends(load_reminder),
    db: AsyncSession = DbSession,
) -> ReminderDetail:
    return await _detail(db, reminder)


@router.patch("/reminders/{reminder_id}", response_model=ReminderDetail)
async def update_reminder(
    body: ReminderUpdate,
    reminder: Reminder = Depends(load_reminder),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> ReminderDetail:
    await _require(db, user, reminder.project_id, workspace_id, Perm.REMINDER_MANAGE)
    data = body.model_dump(exclude_unset=True)
    if "timezone" in data and data["timezone"]:
        _check_timezone(data["timezone"])
    if "channel_id" in data:
        await _check_channel(db, user, workspace_id, reminder.project_id, data["channel_id"])
    for field, value in data.items():
        setattr(reminder, field, value)

    task = await db.get(Task, reminder.task_id)
    if reminder.status == ReminderStatus.ACTIVE and not service.plan_initial(
        reminder, task, now=datetime.now(UTC)
    ):
        service.stop(reminder, "расписание отработано")
    await db.flush()
    return await _detail(db, reminder)


@router.post("/reminders/{reminder_id}/snooze", response_model=ReminderDetail)
async def snooze_reminder(
    body: SnoozeRequest,
    reminder: Reminder = Depends(load_reminder),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> ReminderDetail:
    """Перенести ближайшее напоминание, не трогая расписание."""
    await _require(db, user, reminder.project_id, workspace_id, Perm.REMINDER_MANAGE)
    if reminder.status != ReminderStatus.ACTIVE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reminder is not active")
    base = reminder.next_fire_at or datetime.now(UTC)
    until = body.until
    if until is not None and until.tzinfo is None:
        # Момент без пояса читаем в поясе напоминания, а не сервера.
        until = until.replace(tzinfo=ZoneInfo(reminder.timezone))
    reminder.next_fire_at = until or base + timedelta(days=body.days)
    await db.flush()
    return await _detail(db, reminder)


@router.post("/reminders/{reminder_id}/stop", response_model=ReminderDetail)
async def stop_reminder(
    reminder: Reminder = Depends(load_reminder),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> ReminderDetail:
    await _require(db, user, reminder.project_id, workspace_id, Perm.REMINDER_MANAGE)
    service.stop(reminder, f"снято вручную ({user.name})", status=ReminderStatus.CANCELLED)
    await db.flush()
    return await _detail(db, reminder)


# --------------------------------------------------------------------------- #
# Каналы проекта
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/channels", response_model=list[ChannelOut])
async def list_channels(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.PROJECT_VIEW)),
    db: AsyncSession = DbSession,
) -> list[ChannelOut]:
    rows = await db.scalars(
        select(ProjectChannel)
        .where(ProjectChannel.project_id == project_id)
        .order_by(ProjectChannel.is_default.desc(), ProjectChannel.name)
    )
    return [ChannelOut.model_validate(c) for c in rows.all()]


@router.post(
    "/projects/{project_id}/channels",
    response_model=ChannelOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    project_id: UUID,
    body: ChannelCreate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.CHANNEL_MANAGE)),
    db: AsyncSession = DbSession,
) -> ChannelOut:
    if body.is_default:
        await _unset_default(db, project_id)
    channel = ProjectChannel(
        workspace_id=workspace_id,
        project_id=project_id,
        created_by_id=user.id,
        **body.model_dump(),
    )
    db.add(channel)
    await db.flush()
    return ChannelOut.model_validate(channel)


@router.patch("/channels/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: UUID,
    body: ChannelUpdate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> ChannelOut:
    channel = await db.get(ProjectChannel, channel_id)
    if channel is None or channel.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    await _require(db, user, channel.project_id, workspace_id, Perm.CHANNEL_MANAGE)
    data = body.model_dump(exclude_unset=True)
    if data.get("is_default"):
        await _unset_default(db, channel.project_id)
    for field, value in data.items():
        setattr(channel, field, value)
    await db.flush()
    return ChannelOut.model_validate(channel)


async def _unset_default(db: AsyncSession, project_id: UUID) -> None:
    rows = await db.scalars(
        select(ProjectChannel).where(
            ProjectChannel.project_id == project_id, ProjectChannel.is_default.is_(True)
        )
    )
    for other in rows.all():
        other.is_default = False


# --------------------------------------------------------------------------- #
# Исходящая очередь — интерфейс релея
# --------------------------------------------------------------------------- #


@router.get("/outbox/pending", response_model=list[OutboxOut])
async def pending_messages(
    limit: int = 20,
    _: None = Depends(require_workspace_permission(Perm.WORKSPACE_MANAGE)),
    db: AsyncSession = DbSession,
) -> list[OutboxOut]:
    rows = await db.scalars(
        select(OutboxMessage)
        .where(OutboxMessage.status == OutboxStatus.PENDING)
        .order_by(OutboxMessage.scheduled_for)
        .limit(min(limit, 100))
    )
    return [OutboxOut.model_validate(m) for m in rows.all()]


@router.post("/outbox/{message_id}/sent", response_model=OutboxOut)
async def mark_sent(
    message_id: UUID,
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_workspace_permission(Perm.WORKSPACE_MANAGE)),
    db: AsyncSession = DbSession,
) -> OutboxOut:
    message = await _load_message(db, message_id, workspace_id)
    message.status = OutboxStatus.SENT
    message.sent_at = datetime.now(UTC)
    message.attempts += 1
    message.error = None
    await db.flush()
    return OutboxOut.model_validate(message)


@router.post("/outbox/{message_id}/failed", response_model=OutboxOut)
async def mark_failed(
    message_id: UUID,
    error: str = "",
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_workspace_permission(Perm.WORKSPACE_MANAGE)),
    db: AsyncSession = DbSession,
) -> OutboxOut:
    """Неудача релея. Пока попытки не исчерпаны, сообщение остаётся в очереди."""
    message = await _load_message(db, message_id, workspace_id)
    message.attempts += 1
    message.error = error[:2000] or None
    if message.attempts >= MAX_ATTEMPTS:
        message.status = OutboxStatus.FAILED
    await db.flush()
    return OutboxOut.model_validate(message)


async def _load_message(db: AsyncSession, message_id: UUID, workspace_id: UUID) -> OutboxMessage:
    message = await db.get(OutboxMessage, message_id)
    if message is None or message.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    return message
