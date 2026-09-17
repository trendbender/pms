from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id
from app.models.audit import ActivityLog
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.modules.audit.service import record_activity
from app.modules.notifications.service import notify
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.tasks import service
from app.modules.tasks.schemas import (
    ActivityOut,
    BoardOut,
    MoveTask,
    StatusChange,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)

router = APIRouter(tags=["tasks"])


# --------------------------------------------------------------------------- #
# Dependencies / helpers
# --------------------------------------------------------------------------- #


async def load_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Fetch a live task the user may *see*. Hidden projects read as 404 (spec §7)."""
    task = await db.get(Task, task_id)
    if task is None or task.workspace_id != workspace_id or task.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if not await service.user_can_view_project(db, user.id, workspace_id, task.project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


async def _require(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, project_id: UUID, perm: Perm
) -> None:
    if not await perms.has_project_permission(db, user_id, workspace_id, project_id, perm):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")


async def _validate_participant(
    db: AsyncSession, workspace_id: UUID, project_id: UUID, user_id: UUID, field: str
) -> None:
    """Assignee/reviewer must be able to see the project they are put on (spec §7)."""
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(422, f"{field}: user not found")
    if not await service.user_can_view_project(db, user_id, workspace_id, project_id):
        raise HTTPException(422, f"{field}: user has no access to this project")


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    project = await db.get(Project, body.project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    # visibility first (404), then create right (403)
    if not await service.user_can_view_project(db, user.id, workspace_id, project.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    await _require(db, user.id, workspace_id, project.id, Perm.TASK_CREATE)

    # resolve / validate type
    type_id = body.type_id
    if type_id is None:
        type_id = await service._default_type_id(db, project.id)
        if type_id is None:
            raise HTTPException(422, "project has no task types configured")
    elif not await service.validate_type(db, project.id, type_id):
        raise HTTPException(422, "type_id does not belong to this project")

    # resolve / validate status
    status_id = body.status_id
    if status_id is None:
        status_id = await service._default_status_id(db, project.id)
        if status_id is None:
            raise HTTPException(422, "project has no statuses configured")
    elif await service.validate_status(db, project.id, status_id) is None:
        raise HTTPException(422, "status_id does not belong to this project")

    if body.assignee_id is not None:
        await _validate_participant(db, workspace_id, project.id, body.assignee_id, "assignee_id")
    if body.reviewer_id is not None:
        await _validate_participant(db, workspace_id, project.id, body.reviewer_id, "reviewer_id")

    if body.parent_id is not None:
        parent = await db.get(Task, body.parent_id)
        if parent is None or parent.project_id != project.id:
            raise HTTPException(422, "parent_id must be a task in the same project")
    if body.sprint_id is not None and not await service.validate_sprint(
        db, project.id, body.sprint_id
    ):
        raise HTTPException(422, "sprint_id does not belong to this project")
    if body.initiative_id is not None and not await service.validate_initiative(
        db, project.id, body.initiative_id
    ):
        raise HTTPException(422, "initiative_id does not belong to this project")

    task = await service.create_task(
        db,
        project=project,
        reporter_id=user.id,
        title=body.title,
        description=body.description,
        type_id=type_id,
        status_id=status_id,
        priority=body.priority.value,
        assignee_id=body.assignee_id,
        reviewer_id=body.reviewer_id,
        parent_id=body.parent_id,
        initiative_id=body.initiative_id,
        sprint_id=body.sprint_id,
        acceptance_criteria=body.acceptance_criteria,
        definition_of_done=body.definition_of_done,
        story_points=body.story_points,
        start_at=body.start_at,
        due_at=body.due_at,
    )
    label = f"{task.key}: {task.title}"
    await notify(
        db, workspace_id=workspace_id, user_id=task.assignee_id, actor_id=user.id,
        kind="task.assigned", title=label, task_id=task.id,
    )
    await notify(
        db, workspace_id=workspace_id, user_id=task.reviewer_id, actor_id=user.id,
        kind="review.requested", title=label, task_id=task.id,
    )
    return await service.get_task_out(db, task)


@router.get("/tasks/by-key/{key}", response_model=TaskOut)
async def get_task_by_key(
    key: str,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """Resolve a task by its human key (e.g. ``SSK-23``). Keys are unique per
    workspace, so shared links can avoid exposing the opaque UUID."""
    normalized = key.strip().upper()
    result = await db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            func.upper(Task.key) == normalized,
            Task.deleted_at.is_(None),
        )
    )
    task = result.scalar_one_or_none()
    if task is None or not await service.user_can_view_project(
        db, user.id, workspace_id, task.project_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return await service.get_task_out(db, task)


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task: Task = Depends(load_task),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    return await service.get_task_out(db, task)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    project_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
    status_id: UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    assignee_id: UUID | None = Query(default=None),
    reviewer_id: UUID | None = Query(default=None),
    sprint_id: UUID | None = Query(default=None),
    priority: str | None = Query(default=None),
    type_id: UUID | None = Query(default=None),
) -> list[TaskOut]:
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if not await service.user_can_view_project(db, user.id, workspace_id, project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return await service.list_project_tasks(
        db,
        project_id=project_id,
        status_id=status_id,
        category=category,
        assignee_id=assignee_id,
        reviewer_id=reviewer_id,
        sprint_id=sprint_id,
        priority=priority,
        type_id=type_id,
    )


@router.get("/projects/{project_id}/backlog", response_model=list[TaskOut])
async def get_backlog(
    project_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if not await service.user_can_view_project(db, user.id, workspace_id, project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return await service.list_backlog(db, project_id=project_id)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    body: TaskUpdate,
    task: Task = Depends(load_task),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    fields = body.model_dump(exclude_unset=True)

    # assignment changes require task.assign; everything else task.edit
    assign_fields = {"assignee_id", "reviewer_id"}
    if fields.keys() & assign_fields:
        await _require(db, user.id, workspace_id, task.project_id, Perm.TASK_ASSIGN)
    if fields.keys() - assign_fields:
        await _require(db, user.id, workspace_id, task.project_id, Perm.TASK_EDIT)

    if "type_id" in fields and fields["type_id"] is not None:
        if not await service.validate_type(db, task.project_id, fields["type_id"]):
            raise HTTPException(422, "type_id does not belong to this project")
    for f in ("assignee_id", "reviewer_id"):
        if fields.get(f) is not None:
            await _validate_participant(db, workspace_id, task.project_id, fields[f], f)
    if fields.get("parent_id") is not None:
        parent = await db.get(Task, fields["parent_id"])
        if parent is None or parent.project_id != task.project_id or parent.id == task.id:
            raise HTTPException(422, "parent_id must be another task in the same project")
    if fields.get("sprint_id") is not None and not await service.validate_sprint(
        db, task.project_id, fields["sprint_id"]
    ):
        raise HTTPException(422, "sprint_id does not belong to this project")
    if fields.get("initiative_id") is not None and not await service.validate_initiative(
        db, task.project_id, fields["initiative_id"]
    ):
        raise HTTPException(422, "initiative_id does not belong to this project")

    # activity log for the notable changes (spec §42)
    logged = {
        "assignee_id": "assignee.changed",
        "reviewer_id": "reviewer.changed",
        "priority": "priority.changed",
        "sprint_id": "sprint.changed",
        "due_at": "due_date.changed",
    }
    for field, value in fields.items():
        if field == "priority" and value is not None:
            value = value.value if hasattr(value, "value") else value
        old = getattr(task, field)
        setattr(task, field, value)
        if field in logged and old != getattr(task, field):
            await record_activity(
                db,
                workspace_id=task.workspace_id,
                task_id=task.id,
                actor_id=user.id,
                action=logged[field],
                data={"from": str(old) if old is not None else None,
                      "to": str(value) if value is not None else None},
            )
            if field == "assignee_id" and value is not None:
                await notify(
                    db, workspace_id=task.workspace_id, user_id=value, actor_id=user.id,
                    kind="task.assigned", title=f"{task.key}: {task.title}", task_id=task.id,
                )
            elif field == "reviewer_id" and value is not None:
                await notify(
                    db, workspace_id=task.workspace_id, user_id=value, actor_id=user.id,
                    kind="review.requested", title=f"{task.key}: {task.title}", task_id=task.id,
                )

    await db.flush()
    return await service.get_task_out(db, task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task: Task = Depends(load_task),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require(db, user.id, workspace_id, task.project_id, Perm.TASK_DELETE)
    task.deleted_at = datetime.now(UTC)
    await record_activity(
        db,
        workspace_id=task.workspace_id,
        task_id=task.id,
        actor_id=user.id,
        action="task.deleted",
        data={"key": task.key},
    )
    await db.flush()
    return None


# --------------------------------------------------------------------------- #
# Status transition (Rules 4/5/8)
# --------------------------------------------------------------------------- #


@router.patch("/tasks/{task_id}/status", response_model=TaskOut)
async def change_status(
    body: StatusChange,
    task: Task = Depends(load_task),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    await _require(db, user.id, workspace_id, task.project_id, Perm.TASK_CHANGE_STATUS)
    new_status = await service.validate_status(db, task.project_id, body.status_id)
    if new_status is None:
        raise HTTPException(422, "status_id does not belong to this project")
    await service.change_status(
        db, task=task, new_status=new_status, actor_id=user.id, reason=body.reason
    )
    label = f"{task.key}: {task.title}"
    if new_status.category == "REVIEW":
        await notify(
            db, workspace_id=task.workspace_id, user_id=task.reviewer_id, actor_id=user.id,
            kind="review.requested", title=label, task_id=task.id,
        )
    elif new_status.category == "CHANGES_REQUIRED":
        await notify(
            db, workspace_id=task.workspace_id, user_id=task.assignee_id, actor_id=user.id,
            kind="changes.requested", title=label, task_id=task.id,
        )
    return await service.get_task_out(db, task)


# --------------------------------------------------------------------------- #
# Board & drag-and-drop reordering (§23, §25, §56)
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/board", response_model=BoardOut)
async def get_board(
    project_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> BoardOut:
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if not await service.user_can_view_project(db, user.id, workspace_id, project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return await service.get_board(db, project)


@router.patch("/tasks/{task_id}/position", response_model=TaskOut)
async def move_task(
    body: MoveTask,
    task: Task = Depends(load_task),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    await _require(db, user.id, workspace_id, task.project_id, Perm.TASK_CHANGE_STATUS)
    new_status = await service.validate_status(db, task.project_id, body.status_id)
    if new_status is None:
        raise HTTPException(422, "status_id does not belong to this project")
    for ref in (body.after_id, body.before_id):
        if ref is not None:
            neighbour = await db.get(Task, ref)
            if neighbour is None or neighbour.project_id != task.project_id:
                raise HTTPException(422, "neighbour task must be in the same project")
    await service.move_task(
        db,
        task=task,
        new_status=new_status,
        after_id=body.after_id,
        before_id=body.before_id,
        actor_id=user.id,
        reason=body.reason,
    )
    return await service.get_task_out(db, task)


# --------------------------------------------------------------------------- #
# Activity feed
# --------------------------------------------------------------------------- #


@router.get("/tasks/{task_id}/activity", response_model=list[ActivityOut])
async def task_activity(
    task: Task = Depends(load_task),
    db: AsyncSession = Depends(get_db),
) -> list[ActivityLog]:
    return list(
        (
            await db.scalars(
                select(ActivityLog)
                .where(ActivityLog.task_id == task.id)
                .order_by(ActivityLog.created_at.desc())
            )
        ).all()
    )
