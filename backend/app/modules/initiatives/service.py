"""Initiative services: listing with per-initiative task progress."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StatusCategory
from app.models.initiative import Initiative
from app.models.task import Task, TaskStatus
from app.modules.initiatives.schemas import InitiativeOut


async def _counts(db: AsyncSession, project_id: UUID) -> dict[UUID, tuple[int, int]]:
    """Per-initiative (total, done) task counts for a project (non-deleted tasks)."""
    done_case = func.count(1).filter(TaskStatus.category == StatusCategory.DONE.value)
    rows = await db.execute(
        select(Task.initiative_id, func.count(1), done_case)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(
            Task.project_id == project_id,
            Task.initiative_id.is_not(None),
            Task.deleted_at.is_(None),
        )
        .group_by(Task.initiative_id)
    )
    return {iid: (total, done or 0) for iid, total, done in rows.all()}


async def list_initiatives(db: AsyncSession, project_id: UUID) -> list[InitiativeOut]:
    counts = await _counts(db, project_id)
    initiatives = (
        await db.scalars(
            select(Initiative)
            .where(Initiative.project_id == project_id, Initiative.archived_at.is_(None))
            .order_by(Initiative.created_at)
        )
    ).all()
    out = []
    for i in initiatives:
        total, done = counts.get(i.id, (0, 0))
        out.append(
            InitiativeOut(
                id=i.id,
                project_id=i.project_id,
                name=i.name,
                description=i.description,
                task_count=total,
                done_count=done,
                archived_at=i.archived_at,
                created_at=i.created_at,
            )
        )
    return out


async def _single_counts(db: AsyncSession, initiative_id: UUID) -> tuple[int, int]:
    """(total, done) task counts for one initiative (non-deleted tasks)."""
    done_case = func.count(1).filter(TaskStatus.category == StatusCategory.DONE.value)
    total, done = (
        await db.execute(
            select(func.count(1), done_case)
            .join(TaskStatus, TaskStatus.id == Task.status_id)
            .where(Task.initiative_id == initiative_id, Task.deleted_at.is_(None))
        )
    ).one()
    return total, done or 0


async def get_out(db: AsyncSession, i: Initiative) -> InitiativeOut:
    total, done = await _single_counts(db, i.id)
    return to_out(i, total, done)


def to_out(i: Initiative, task_count: int = 0, done_count: int = 0) -> InitiativeOut:
    return InitiativeOut(
        id=i.id,
        project_id=i.project_id,
        name=i.name,
        description=i.description,
        task_count=task_count,
        done_count=done_count,
        archived_at=i.archived_at,
        created_at=i.created_at,
    )
