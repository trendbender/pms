"""API инбокса: положить входящее, посмотреть очередь разбора, разобрать.

Приёма по анонимному ключу здесь нет сознательно, в отличие от лидов. ИИ и боты
ходят в PMS под своими аккаунтами (решение P-004) — тогда в журнале видно, чьё
это сырьё, и права агента ограничены его проектами. Ключ приёма дал бы
обезличенный поток, то есть ровно ту потерю следа, из-за которой агентам и
завели аккаунты.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import DbSession
from app.core.deps import get_current_user, get_workspace_id
from app.models.enums import INBOX_OUTCOMES_WITH_TASK, InboxOutcome, InboxStatus, Priority
from app.models.inbox import InboxItem
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.modules.inbox import service
from app.modules.inbox.schemas import (
    InboxCount,
    InboxCreate,
    InboxOut,
    InboxProjectCount,
    InboxResolve,
    InboxUpdate,
)
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm

router = APIRouter(tags=["inbox"])


async def _project_for_write(
    db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID, perm: Perm
) -> Project:
    """Проект, в инбокс которого человек вправе писать. Нет прав видеть — 404
    (§7: существование проекта не раскрываем), есть видеть, но не это — 403."""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if not await perms.has_project_permission(db, user.id, workspace_id, project_id, perm):
        if not await perms.has_project_permission(
            db, user.id, workspace_id, project_id, Perm.INBOX_VIEW
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")
    return project


async def load_item(
    item_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> InboxItem:
    item = await db.get(InboxItem, item_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inbox item not found")
    allowed = await service.inbox_project_ids(db, user.id, workspace_id)
    if not service.can_see_item(item, user.id, allowed):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inbox item not found")
    return item


async def _out(db: AsyncSession, item: InboxItem) -> InboxOut:
    out = InboxOut.model_validate(item)
    if item.project_id:
        out.project_code = await db.scalar(
            select(Project.code).where(Project.id == item.project_id)
        )
    if item.task_id:
        out.task_key = await db.scalar(select(Task.key).where(Task.id == item.task_id))
    return out


async def _capture(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    body: InboxCreate,
    project_id: UUID | None,
) -> InboxOut:
    if project_id is not None:
        await _project_for_write(db, user, workspace_id, project_id, Perm.INBOX_MANAGE)
    elif not await perms.has_workspace_permission(
        db, user.id, workspace_id, Perm.WORKSPACE_VIEW
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: workspace.view")

    if body.external_id and project_id is not None:
        twin = await service.find_duplicate(
            db, project_id=project_id, source=body.source, external_id=body.external_id
        )
        if twin is not None:
            # Повтор отчёта или вебхука отдаёт уже лежащий пункт, а не второй:
            # разбирать одно и то же дважды — это и есть шум.
            return await _out(db, twin)

    data = body.model_dump(exclude={"project_id"})
    try:
        # savepoint: проигравшая гонку вставка не должна ронять всю транзакцию
        async with db.begin_nested():
            item = await service.capture(
                db, workspace_id=workspace_id, actor_id=user.id, project_id=project_id, **data
            )
    except IntegrityError as exc:
        # Два одинаковых вебхука разом: второй проиграл гонку на uq_inbox_external.
        # Отдаём ему тот пункт, который лёг первым — повтор идемпотентен и в гонке.
        twin = (
            await service.find_duplicate(
                db,
                project_id=project_id,
                source=body.source,
                external_id=body.external_id,
            )
            if (body.external_id and project_id is not None)
            else None
        )
        if twin is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Inbox item with this external_id already exists"
            ) from exc
        return await _out(db, twin)
    return await _out(db, item)


@router.post("/inbox", response_model=InboxOut, status_code=status.HTTP_201_CREATED)
async def capture_item(
    body: InboxCreate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> InboxOut:
    """Положить входящее. Без `project_id` пункт личный: его видят автор и адресат."""
    return await _capture(db, user, workspace_id, body, body.project_id)


@router.post(
    "/projects/{project_id}/inbox",
    response_model=InboxOut,
    status_code=status.HTTP_201_CREATED,
)
async def capture_project_item(
    project_id: UUID,
    body: InboxCreate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> InboxOut:
    """То же, но проект берётся из пути — так входящее кладут боты и отчёты."""
    return await _capture(db, user, workspace_id, body, project_id)


@router.get("/inbox", response_model=list[InboxOut])
async def list_inbox(
    project_id: UUID | None = None,
    item_status: InboxStatus = Query(default=InboxStatus.NEW, alias="status"),
    source: str | None = None,
    mine_only: bool = False,
    limit: int = 200,
    offset: int = 0,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> list[InboxOut]:
    """Очередь разбора по всем видимым проектам плюс свои личные пункты.

    По умолчанию отдаёт только неразобранное: инбокс — это то, что ждёт решения,
    а разобранное остаётся историей и запрашивается явно.
    """
    allowed = await service.inbox_project_ids(db, user.id, workspace_id)
    if project_id is not None:
        if project_id not in allowed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        allowed = {project_id}

    query = select(InboxItem).where(
        InboxItem.workspace_id == workspace_id,
        InboxItem.status == item_status.value,
    )
    personal = (InboxItem.project_id.is_(None)) & (
        (InboxItem.created_by_id == user.id) | (InboxItem.for_user_id == user.id)
    )
    if project_id is not None:
        query = query.where(InboxItem.project_id == project_id)
    elif allowed:
        query = query.where((InboxItem.project_id.in_(allowed)) | personal)
    else:
        query = query.where(personal)

    if source:
        query = query.where(InboxItem.source == source)
    if mine_only:
        query = query.where(InboxItem.for_user_id == user.id)

    rows = await db.scalars(
        query.order_by(InboxItem.created_at).limit(min(limit, 500)).offset(offset)
    )
    return [await _out(db, item) for item in rows.all()]


@router.get("/inbox/count", response_model=InboxCount)
async def inbox_count(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> InboxCount:
    """Сколько ждёт разбора — для счётчика в навигации и утреннего дайджеста."""
    allowed = await service.inbox_project_ids(db, user.id, workspace_id)
    personal = (InboxItem.project_id.is_(None)) & (
        (InboxItem.created_by_id == user.id) | (InboxItem.for_user_id == user.id)
    )
    scope = (InboxItem.project_id.in_(allowed)) | personal if allowed else personal
    rows = (
        await db.execute(
            select(InboxItem.project_id, Project.code, func.count(InboxItem.id))
            .join(Project, Project.id == InboxItem.project_id, isouter=True)
            .where(
                InboxItem.workspace_id == workspace_id,
                InboxItem.status == InboxStatus.NEW.value,
                scope,
            )
            .group_by(InboxItem.project_id, Project.code)
            .order_by(func.count(InboxItem.id).desc())
        )
    ).all()
    return InboxCount(
        new=sum(count for _, _, count in rows),
        by_project=[
            InboxProjectCount(project_id=pid, project_code=code, new=count)
            for pid, code, count in rows
        ],
    )


@router.get("/inbox/{item_id}", response_model=InboxOut)
async def get_item(
    item: InboxItem = Depends(load_item),
    db: AsyncSession = DbSession,
) -> InboxOut:
    return await _out(db, item)


@router.patch("/inbox/{item_id}", response_model=InboxOut)
async def update_item(
    body: InboxUpdate,
    item: InboxItem = Depends(load_item),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> InboxOut:
    """Уточнить сырьё до разбора: формулировку, проект, адресата.

    Разобранный пункт не правится: исход — это запись о том, чем кончилось
    входящее, а не поле карточки.
    """
    if item.status != InboxStatus.NEW.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Item is already resolved")
    await _require_manage(db, user, workspace_id, item)

    data = body.model_dump(exclude_unset=True)
    if data.get("project_id") is not None and data["project_id"] != item.project_id:
        await _project_for_write(db, user, workspace_id, data["project_id"], Perm.INBOX_MANAGE)
    for field, value in data.items():
        setattr(item, field, value)
    await db.flush()
    return await _out(db, item)


@router.post("/inbox/{item_id}/resolve", response_model=InboxOut)
async def resolve_item(
    body: InboxResolve,
    item: InboxItem = Depends(load_item),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> InboxOut:
    """Разобрать пункт одним из шести исходов (P-002).

    Исходы, заводящие задачу, требуют проект и свою формулировку следующего
    действия; «в календарь» — ещё и дату-обязательство. Это и есть правило
    разбора, вынесенное в API: календарь, в котором половину можно не делать,
    перестаёт быть календарём.
    """
    if item.status != InboxStatus.NEW.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Item is already resolved")
    await _require_manage(db, user, workspace_id, item)

    project: Project | None = None
    if body.outcome in INBOX_OUTCOMES_WITH_TASK:
        project_id = body.project_id or item.project_id
        if project_id is None:
            raise HTTPException(422, "нужен project_id: задача не бывает вне проекта")
        project = await _project_for_write(db, user, workspace_id, project_id, Perm.TASK_CREATE)
        for who in (body.assignee_id, body.reviewer_id):
            if who is not None and not await perms.has_project_permission(
                db, who, workspace_id, project.id, Perm.TASK_VIEW
            ):
                raise HTTPException(422, "assignee or reviewer has no project access")

    try:
        await service.resolve(
            db,
            item=item,
            project=project,
            actor_id=user.id,
            outcome=InboxOutcome(body.outcome),
            note=body.note,
            title=body.title,
            description=body.description,
            priority=Priority(body.priority).value,
            assignee_id=body.assignee_id,
            reviewer_id=body.reviewer_id,
            initiative_id=body.initiative_id,
            start_at=body.start_at,
            due_at=body.due_at,
            reference_url=body.reference_url,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _out(db, item)


async def _require_manage(
    db: AsyncSession, user: User, workspace_id: UUID, item: InboxItem
) -> None:
    """Разбирать пункт проекта вправе участник проекта; личный — только его автор
    или адресат (их уже отфильтровала видимость)."""
    if item.project_id is None:
        return
    if not await perms.has_project_permission(
        db, user.id, workspace_id, item.project_id, Perm.INBOX_MANAGE
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Missing permission: {Perm.INBOX_MANAGE}"
        )
