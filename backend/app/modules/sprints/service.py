"""Sprint services: planning, start (Rule 6 + single active sprint), completion
with carry-over of incomplete work (spec §26–§29)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SprintStatus, StatusCategory
from app.models.sprint import Sprint
from app.models.task import Task, TaskStatus
from app.modules.sprints.schemas import SprintOut, SprintStats

DEFAULT_SPRINT_DAYS = 14


async def stats(db: AsyncSession, sprint_id: UUID) -> SprintStats:
    """Task counts for a sprint by status category (non-deleted tasks)."""
    rows = await db.execute(
        select(TaskStatus.category, func.count(1))
        .select_from(Task)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(Task.sprint_id == sprint_id, Task.deleted_at.is_(None))
        .group_by(TaskStatus.category)
    )
    by_cat = {cat: n for cat, n in rows.all()}
    total = sum(by_cat.values())
    done = by_cat.get(StatusCategory.DONE.value, 0)
    in_progress = by_cat.get(StatusCategory.IN_PROGRESS.value, 0)
    blocked = by_cat.get(StatusCategory.BLOCKED.value, 0)
    todo = total - done - in_progress - blocked
    return SprintStats(
        total=total, done=done, in_progress=in_progress, blocked=blocked, todo=todo
    )


def to_out(sprint: Sprint, s: SprintStats) -> SprintOut:
    return SprintOut(
        id=sprint.id,
        project_id=sprint.project_id,
        name=sprint.name,
        goal=sprint.goal,
        status=sprint.status,
        start_date=sprint.start_date,
        end_date=sprint.end_date,
        created_at=sprint.created_at,
        stats=s,
    )


async def list_sprints(db: AsyncSession, project_id: UUID) -> list[SprintOut]:
    sprints = (
        await db.scalars(
            select(Sprint)
            .where(Sprint.project_id == project_id)
            .order_by(Sprint.created_at.desc())
        )
    ).all()
    return [to_out(sp, await stats(db, sp.id)) for sp in sprints]


async def active_sprint_id(db: AsyncSession, project_id: UUID) -> UUID | None:
    return await db.scalar(
        select(Sprint.id).where(
            Sprint.project_id == project_id,
            Sprint.status == SprintStatus.ACTIVE.value,
        )
    )


async def start_sprint(db: AsyncSession, sprint: Sprint) -> None:
    """Rule 6: a sprint needs a goal. Only one sprint may be ACTIVE per project."""
    if sprint.status == SprintStatus.ACTIVE.value:
        return
    if sprint.status in (SprintStatus.COMPLETED.value, SprintStatus.CANCELLED.value):
        raise ValueError("sprint already finished")
    if not (sprint.goal and sprint.goal.strip()):
        raise ValueError("sprint needs a goal before it can start")
    existing = await active_sprint_id(db, sprint.project_id)
    if existing is not None and existing != sprint.id:
        raise PermissionError("another sprint is already active")

    now = datetime.now(UTC)
    sprint.status = SprintStatus.ACTIVE.value
    if sprint.start_date is None:
        sprint.start_date = now
    if sprint.end_date is None:
        sprint.end_date = (sprint.start_date or now) + timedelta(days=DEFAULT_SPRINT_DAYS)
    await db.flush()


async def complete_sprint(
    db: AsyncSession, sprint: Sprint, next_sprint_id: UUID | None
) -> tuple[int, int, str]:
    """Close a sprint. Incomplete (non-DONE) tasks carry to next_sprint_id or the
    backlog (sprint_id cleared). Returns (completed, moved, moved_to)."""
    done_status_ids = select(TaskStatus.id).where(
        TaskStatus.project_id == sprint.project_id,
        TaskStatus.category == StatusCategory.DONE.value,
    )
    tasks = (
        await db.scalars(
            select(Task).where(Task.sprint_id == sprint.id, Task.deleted_at.is_(None))
        )
    ).all()
    done_ids = set((await db.scalars(done_status_ids)).all())

    target: UUID | None = None
    moved_to = "backlog"
    if next_sprint_id is not None:
        target = next_sprint_id
        moved_to = str(next_sprint_id)

    completed = 0
    moved = 0
    for task in tasks:
        if task.status_id in done_ids:
            completed += 1
        else:
            task.sprint_id = target
            moved += 1

    sprint.status = SprintStatus.COMPLETED.value
    sprint.end_date = datetime.now(UTC)
    await db.flush()
    return completed, moved, moved_to
