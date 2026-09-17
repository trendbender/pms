"""Task domain services: creation (key/number allocation, workflow defaults),
listing with filters, status transitions with review/blocker/done semantics."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StatusCategory
from app.models.project import Project
from app.models.task import Task, TaskStatus, TaskType
from app.modules.audit.service import record_activity
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.tasks.schemas import TaskOut


async def user_can_view_project(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, project_id: UUID
) -> bool:
    return await perms.has_project_permission(
        db, user_id, workspace_id, project_id, Perm.PROJECT_VIEW
    )


async def _default_type_id(db: AsyncSession, project_id: UUID) -> UUID | None:
    return await db.scalar(
        select(TaskType.id)
        .where(TaskType.project_id == project_id)
        .order_by(TaskType.position)
        .limit(1)
    )


async def _default_status_id(db: AsyncSession, project_id: UUID) -> UUID | None:
    """First BACKLOG-category status, falling back to the lowest-positioned one."""
    sid = await db.scalar(
        select(TaskStatus.id)
        .where(
            TaskStatus.project_id == project_id,
            TaskStatus.category == StatusCategory.BACKLOG.value,
        )
        .order_by(TaskStatus.position)
        .limit(1)
    )
    if sid is not None:
        return sid
    return await db.scalar(
        select(TaskStatus.id)
        .where(TaskStatus.project_id == project_id)
        .order_by(TaskStatus.position)
        .limit(1)
    )


async def validate_type(db: AsyncSession, project_id: UUID, type_id: UUID) -> bool:
    row = await db.scalar(select(TaskType.id).where(TaskType.id == type_id))
    if row is None:
        return False
    owner = await db.scalar(select(TaskType.project_id).where(TaskType.id == type_id))
    return owner == project_id


async def validate_status(db: AsyncSession, project_id: UUID, status_id: UUID) -> TaskStatus | None:
    st = await db.get(TaskStatus, status_id)
    if st is None or st.project_id != project_id:
        return None
    return st


async def validate_sprint(db: AsyncSession, project_id: UUID, sprint_id: UUID) -> bool:
    from app.models.sprint import Sprint

    owner = await db.scalar(select(Sprint.project_id).where(Sprint.id == sprint_id))
    return owner == project_id


async def validate_initiative(db: AsyncSession, project_id: UUID, initiative_id: UUID) -> bool:
    from app.models.initiative import Initiative

    owner = await db.scalar(select(Initiative.project_id).where(Initiative.id == initiative_id))
    return owner == project_id


def _out_from_row(task: Task, status_name, status_category, type_name) -> TaskOut:
    return TaskOut(
        id=task.id,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        number=task.number,
        key=task.key,
        parent_id=task.parent_id,
        initiative_id=task.initiative_id,
        title=task.title,
        description=task.description,
        type_id=task.type_id,
        type_name=type_name,
        status_id=task.status_id,
        status_name=status_name,
        status_category=status_category,
        priority=task.priority,
        assignee_id=task.assignee_id,
        reviewer_id=task.reviewer_id,
        reporter_id=task.reporter_id,
        sprint_id=task.sprint_id,
        acceptance_criteria=task.acceptance_criteria,
        definition_of_done=task.definition_of_done,
        story_points=task.story_points,
        is_blocked=task.is_blocked,
        blocked_reason=task.blocked_reason,
        start_at=task.start_at,
        due_at=task.due_at,
        completed_at=task.completed_at,
        position=float(task.position),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _base_task_query() -> Select:
    return (
        select(
            Task,
            TaskStatus.name.label("status_name"),
            TaskStatus.category.label("status_category"),
            TaskType.name.label("type_name"),
        )
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .join(TaskType, TaskType.id == Task.type_id)
        .where(Task.deleted_at.is_(None))
    )


async def get_task_out(db: AsyncSession, task: Task) -> TaskOut:
    row = (await db.execute(_base_task_query().where(Task.id == task.id))).first()
    if row is None:  # e.g. just soft-deleted
        return _out_from_row(task, None, None, None)
    t, sname, scat, tname = row
    return _out_from_row(t, sname, scat, tname)


async def create_task(
    db: AsyncSession,
    *,
    project: Project,
    reporter_id: UUID,
    title: str,
    description: str | None,
    type_id: UUID,
    status_id: UUID,
    priority: str,
    assignee_id: UUID | None,
    reviewer_id: UUID | None,
    parent_id: UUID | None,
    initiative_id: UUID | None,
    sprint_id: UUID | None,
    acceptance_criteria: str | None,
    definition_of_done: str | None,
    story_points: int | None,
    start_at: datetime | None,
    due_at: datetime | None,
) -> Task:
    # allocate the next per-project number and build the workspace-unique key
    project.task_counter += 1
    number = project.task_counter
    key = f"{project.code}-{number}"

    # place at the TOP of the target column (fractional ordering): the board sorts
    # by ascending position, so a value below the current minimum floats it up.
    min_pos = await db.scalar(
        select(Task.position)
        .where(Task.status_id == status_id, Task.deleted_at.is_(None))
        .order_by(Task.position.asc())
        .limit(1)
    )
    position = float(min_pos) - 1000 if min_pos is not None else 1000.0

    task = Task(
        workspace_id=project.workspace_id,
        project_id=project.id,
        number=number,
        key=key,
        title=title,
        description=description,
        type_id=type_id,
        status_id=status_id,
        priority=priority,
        assignee_id=assignee_id,
        reviewer_id=reviewer_id,
        reporter_id=reporter_id,
        parent_id=parent_id,
        initiative_id=initiative_id,
        sprint_id=sprint_id,
        acceptance_criteria=acceptance_criteria,
        definition_of_done=definition_of_done,
        story_points=story_points,
        start_at=start_at,
        due_at=due_at,
        position=position,
    )
    db.add(task)
    await db.flush()

    await record_activity(
        db,
        workspace_id=project.workspace_id,
        task_id=task.id,
        actor_id=reporter_id,
        action="task.created",
        data={"key": key, "title": title},
    )
    return task


async def list_project_tasks(
    db: AsyncSession,
    *,
    project_id: UUID,
    status_id: UUID | None = None,
    category: str | None = None,
    assignee_id: UUID | None = None,
    reviewer_id: UUID | None = None,
    sprint_id: UUID | None = None,
    priority: str | None = None,
    type_id: UUID | None = None,
    initiative_id: UUID | None = None,
) -> list[TaskOut]:
    q = _base_task_query().where(Task.project_id == project_id)
    if initiative_id is not None:
        q = q.where(Task.initiative_id == initiative_id)
    if status_id is not None:
        q = q.where(Task.status_id == status_id)
    if category is not None:
        q = q.where(TaskStatus.category == category)
    if assignee_id is not None:
        q = q.where(Task.assignee_id == assignee_id)
    if reviewer_id is not None:
        q = q.where(Task.reviewer_id == reviewer_id)
    if sprint_id is not None:
        q = q.where(Task.sprint_id == sprint_id)
    if priority is not None:
        q = q.where(Task.priority == priority)
    if type_id is not None:
        q = q.where(Task.type_id == type_id)
    q = q.order_by(TaskStatus.position, Task.position)
    rows = (await db.execute(q)).all()
    return [_out_from_row(t, sname, scat, tname) for t, sname, scat, tname in rows]


_PRIORITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}


async def list_backlog(db: AsyncSession, *, project_id: UUID) -> list[TaskOut]:
    """Unsprinted, not-yet-done tasks, ordered by priority then manual position (§12)."""
    q = _base_task_query().where(
        Task.project_id == project_id,
        Task.sprint_id.is_(None),
        TaskStatus.category != StatusCategory.DONE.value,
    )
    rows = (await db.execute(q)).all()
    outs = [_out_from_row(t, sname, scat, tname) for t, sname, scat, tname in rows]
    outs.sort(key=lambda t: (_PRIORITY_RANK.get(t.priority, 5), t.position))
    return outs


async def change_status(
    db: AsyncSession,
    *,
    task: Task,
    new_status: TaskStatus,
    actor_id: UUID,
    reason: str | None,
) -> None:
    """Apply a status transition with review/done/blocked semantics (Rules 4, 5, 8)."""
    old_status = await db.get(TaskStatus, task.status_id)
    old_cat = old_status.category if old_status else None
    new_cat = new_status.category

    task.status_id = new_status.id

    # Rule 5 — DONE means accepted: stamp/clear completion.
    if new_cat == StatusCategory.DONE.value:
        task.completed_at = datetime.now(UTC)
    elif old_cat == StatusCategory.DONE.value:
        task.completed_at = None

    # Rule 8 — blocked is visible with a reason.
    if new_cat == StatusCategory.BLOCKED.value:
        task.is_blocked = True
        task.blocked_reason = reason
    else:
        task.is_blocked = False
        task.blocked_reason = None

    await db.flush()
    await record_activity(
        db,
        workspace_id=task.workspace_id,
        task_id=task.id,
        actor_id=actor_id,
        action="status.changed",
        data={
            "from": old_status.name if old_status else None,
            "to": new_status.name,
            "from_category": old_cat,
            "to_category": new_cat,
        },
    )


async def _column_max_position(db: AsyncSession, status_id: UUID, exclude_id: UUID) -> float | None:
    return await db.scalar(
        select(Task.position)
        .where(
            Task.status_id == status_id,
            Task.deleted_at.is_(None),
            Task.id != exclude_id,
        )
        .order_by(Task.position.desc())
        .limit(1)
    )


async def move_task(
    db: AsyncSession,
    *,
    task: Task,
    new_status: TaskStatus,
    after_id: UUID | None,
    before_id: UUID | None,
    actor_id: UUID,
    reason: str | None,
) -> None:
    """Move a task to a column and slot it between two neighbours (spec §56).

    Dragging into a different column is a real status change, so it carries the
    Rule 4/5/8 semantics; a same-column drop just reorders (records task.moved).
    """
    status_changed = task.status_id != new_status.id
    if status_changed:
        await change_status(
            db, task=task, new_status=new_status, actor_id=actor_id, reason=reason
        )

    prev_pos: float | None = None
    next_pos: float | None = None
    if after_id is not None:
        a = await db.get(Task, after_id)
        if a is not None and a.id != task.id:
            prev_pos = float(a.position)
    if before_id is not None:
        b = await db.get(Task, before_id)
        if b is not None and b.id != task.id:
            next_pos = float(b.position)

    if prev_pos is not None and next_pos is not None:
        new_pos = (prev_pos + next_pos) / 2
    elif prev_pos is not None:
        new_pos = prev_pos + 1000
    elif next_pos is not None:
        new_pos = next_pos - 1000
    else:
        # no neighbours given -> append to the bottom of the target column
        max_pos = await _column_max_position(db, new_status.id, task.id)
        new_pos = (float(max_pos) + 1000) if max_pos is not None else 1000.0

    task.position = new_pos
    await db.flush()

    if not status_changed:
        await record_activity(
            db,
            workspace_id=task.workspace_id,
            task_id=task.id,
            actor_id=actor_id,
            action="task.moved",
            data={"status": new_status.name, "position": new_pos},
        )


async def get_board(db: AsyncSession, project: Project) -> dict:
    """Columns (ordered statuses) each carrying their tasks, plus WIP info for
    the IN_PROGRESS column (soft — a warning flag, never a block; spec §25)."""
    statuses = list(
        (
            await db.scalars(
                select(TaskStatus)
                .where(TaskStatus.project_id == project.id)
                .order_by(TaskStatus.position)
            )
        ).all()
    )
    all_tasks = await list_project_tasks(db, project_id=project.id)
    by_status: dict[UUID, list] = {}
    for t in all_tasks:
        by_status.setdefault(t.status_id, []).append(t)

    columns = []
    for st in statuses:
        col_tasks = by_status.get(st.id, [])
        wip_limit = None
        wip_exceeded = False
        if st.category == StatusCategory.IN_PROGRESS.value and project.wip_limit is not None:
            wip_limit = project.wip_limit
            wip_exceeded = len(col_tasks) > project.wip_limit
        columns.append(
            {
                "status_id": st.id,
                "name": st.name,
                "category": st.category,
                "position": st.position,
                "wip_limit": wip_limit,
                "wip_exceeded": wip_exceeded,
                "tasks": col_tasks,
            }
        )
    return {"project_id": project.id, "columns": columns}
