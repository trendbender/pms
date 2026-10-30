"""Инбокс: кому что видно, приём входящего и разбор по шести исходам.

Разбор собран в одном месте намеренно. Исход пишется один раз и остаётся
(`outcome`), поэтому важно, чтобы все шесть ветки проходили через одну функцию:
иначе «сделал сам» и «в мусор» начинают отличаться только тем, кто какой
эндпоинт позвал, и ответ на вопрос «чем кончилось входящее» перестаёт быть
надёжным.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import InboxOutcome, InboxStatus
from app.models.inbox import InboxItem
from app.models.project import Project
from app.models.task import Task
from app.modules.audit.service import record_activity, record_audit
from app.modules.notifications.service import notify
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.projects.service import list_visible_projects
from app.modules.tasks import service as task_service


async def inbox_project_ids(db: AsyncSession, user_id: UUID, workspace_id: UUID) -> set[UUID]:
    """Проекты, чей инбокс человек вправе видеть.

    Это НЕ то же, что видимые проекты: наблюдатель и гость проект видят, а
    инбокс — нет (`inbox.view` есть с уровня участника). Проектов у владельца
    десятки, не тысячи, поэтому права проверяются по одному и без кеша.
    """
    ids = set()
    for project in await list_visible_projects(db, user_id, workspace_id):
        if await perms.has_project_permission(
            db, user_id, workspace_id, project.id, Perm.INBOX_VIEW
        ):
            ids.add(project.id)
    return ids


def can_see_item(item: InboxItem, user_id: UUID, allowed_projects: set[UUID]) -> bool:
    """Пункт проекта видит тот, кто видит инбокс проекта; личный пункт (без
    проекта) — только автор и адресат."""
    if item.project_id is not None:
        return item.project_id in allowed_projects
    return user_id in (item.created_by_id, item.for_user_id)


async def find_duplicate(
    db: AsyncSession, *, project_id: UUID, source: str, external_id: str
) -> InboxItem | None:
    """Тот же внешний id из того же источника — это повтор, а не второй пункт.
    Отчёт, который прогнали дважды, не должен удваивать разбор."""
    return await db.scalar(
        select(InboxItem).where(
            InboxItem.project_id == project_id,
            InboxItem.source == source,
            InboxItem.external_id == external_id,
        )
    )


async def capture(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_id: UUID,
    project_id: UUID | None,
    title: str,
    body: str | None = None,
    url: str | None = None,
    source: str = "manual",
    external_id: str | None = None,
    for_user_id: UUID | None = None,
) -> InboxItem:
    item = InboxItem(
        workspace_id=workspace_id,
        project_id=project_id,
        title=title,
        body=body,
        url=url,
        source=source,
        external_id=external_id,
        for_user_id=for_user_id,
        created_by_id=actor_id,
        status=InboxStatus.NEW.value,
    )
    db.add(item)
    await db.flush()

    await record_audit(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="inbox.captured",
        target_type="inbox_item",
        target_id=item.id,
        data={"source": source, "project_id": str(project_id) if project_id else None},
    )
    # Адресату — тихая отметка в PMS, без прерывания: из «тебе положили сырьё»
    # не следует действие прямо сейчас (правило трёх уровней внимания).
    await notify(
        db,
        workspace_id=workspace_id,
        user_id=for_user_id,
        actor_id=actor_id,
        kind="inbox.captured",
        title=title[:500],
        body=body,
        payload={"inbox_item_id": str(item.id), "source": source},
    )
    return item


async def _create_task_for(
    db: AsyncSession,
    *,
    item: InboxItem,
    project: Project,
    actor_id: UUID,
    outcome: InboxOutcome,
    title: str,
    description: str | None,
    priority: str,
    assignee_id: UUID | None,
    reviewer_id: UUID | None,
    initiative_id: UUID | None,
    start_at: datetime | None,
    due_at: datetime | None,
) -> Task:
    type_id = await task_service._default_type_id(db, project.id)
    status_id = await task_service._default_status_id(db, project.id)
    if type_id is None or status_id is None:
        raise ValueError("Project has no task types or statuses")

    # Сырьё остаётся в описании задачи ссылкой на источник: формулировку
    # действия человек дал сам, но контекст («откуда это взялось») терять нельзя.
    origin = [f"Из инбокса: {item.title}"]
    if item.url:
        origin.append(item.url)
    if item.body:
        origin.append(item.body)
    full_description = "\n\n".join([description, *origin]) if description else "\n\n".join(origin)

    task = await task_service.create_task(
        db,
        project=project,
        reporter_id=actor_id,
        title=title,
        description=full_description,
        type_id=type_id,
        status_id=status_id,
        priority=priority,
        assignee_id=assignee_id,
        reviewer_id=reviewer_id,
        parent_id=None,
        initiative_id=initiative_id,
        sprint_id=None,
        acceptance_criteria=None,
        definition_of_done=None,
        story_points=None,
        start_at=start_at,
        due_at=due_at,
    )
    await record_activity(
        db,
        workspace_id=item.workspace_id,
        task_id=task.id,
        actor_id=actor_id,
        action="task.from_inbox",
        data={"outcome": outcome.value, "inbox_item_id": str(item.id), "source": item.source},
    )
    return task


async def resolve(
    db: AsyncSession,
    *,
    item: InboxItem,
    project: Project | None,
    actor_id: UUID,
    outcome: InboxOutcome,
    note: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: str = "MEDIUM",
    assignee_id: UUID | None = None,
    reviewer_id: UUID | None = None,
    initiative_id: UUID | None = None,
    start_at: datetime | None = None,
    due_at: datetime | None = None,
    reference_url: str | None = None,
) -> InboxItem:
    """Закрыть пункт одним из шести исходов. Проверки «что обязательно для
    какого исхода» живут в схеме `InboxResolve`, здесь — последствия."""
    task: Task | None = None
    if outcome in (InboxOutcome.TASK, InboxOutcome.DELEGATED, InboxOutcome.CALENDAR):
        if project is None or title is None:
            raise ValueError("для этого исхода нужны проект и формулировка действия")
        # Делегирование пока кладёт задачу в обычную колонку с исполнителем.
        # Категории «Жду ответа» в статусах ещё нет (PMS-30): когда появится,
        # ровно здесь выбирается статус этой категории, а не дефолтный.
        task = await _create_task_for(
            db,
            item=item,
            project=project,
            actor_id=actor_id,
            outcome=outcome,
            title=title,
            description=description,
            priority=priority,
            assignee_id=assignee_id,
            reviewer_id=reviewer_id,
            initiative_id=initiative_id,
            # Исход «в календарь» — это обязательство на момент: он же начало
            # работы. Срок без своей даты совпадает с ним, чтобы задача не
            # оказалась одновременно «на вторник» и «без срока».
            start_at=start_at,
            due_at=due_at or (start_at if outcome == InboxOutcome.CALENDAR else None),
        )
        item.task_id = task.id
        if item.project_id is None:
            item.project_id = project.id

    if outcome == InboxOutcome.REFERENCE:
        item.reference_url = reference_url

    item.status = InboxStatus.RESOLVED.value
    item.outcome = outcome.value
    item.outcome_note = note
    item.resolved_at = datetime.now(UTC)
    item.resolved_by_id = actor_id
    await db.flush()

    await record_audit(
        db,
        workspace_id=item.workspace_id,
        actor_id=actor_id,
        action="inbox.resolved",
        target_type="inbox_item",
        target_id=item.id,
        data={
            "outcome": outcome.value,
            "task_key": task.key if task else None,
            "reference_url": item.reference_url,
        },
    )
    # Делегирование — единственный исход, где после разбора кто-то должен узнать:
    # мяч перешёл на его сторону.
    if outcome == InboxOutcome.DELEGATED and task is not None:
        await notify(
            db,
            workspace_id=item.workspace_id,
            user_id=assignee_id,
            actor_id=actor_id,
            kind="task.assigned",
            title=task.title,
            body=f"Делегировано из инбокса: {item.title}",
            task_id=task.id,
            payload={"inbox_item_id": str(item.id), "task_key": task.key},
        )
    return item
