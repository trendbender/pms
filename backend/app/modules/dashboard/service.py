"""Cross-project aggregation for the management screens (spec §31–§35).

All queries are scoped to the projects the user may view, so no data leaks
across permission boundaries.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SprintStatus, StatusCategory
from app.models.project import Project
from app.models.sprint import Sprint
from app.models.task import Task, TaskStatus
from app.modules.dashboard.schemas import (
    PortfolioOut,
    PortfolioRow,
    PortfolioTotals,
    ProjectDashboard,
    SprintBrief,
    TaskCard,
)
from app.modules.projects.service import list_visible_projects

_DONE = StatusCategory.DONE.value
_REVIEW = StatusCategory.REVIEW.value


def _card_query() -> Select:
    return (
        select(
            Task,
            TaskStatus.name.label("status_name"),
            TaskStatus.category.label("status_category"),
            Project.code.label("project_code"),
            Project.name.label("project_name"),
        )
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .join(Project, Project.id == Task.project_id)
        .where(Task.deleted_at.is_(None))
    )


def _to_card(row) -> TaskCard:
    t, sname, scat, pcode, pname = row
    return TaskCard(
        id=t.id,
        key=t.key,
        title=t.title,
        priority=t.priority,
        status_name=sname,
        status_category=scat,
        due_at=t.due_at,
        is_blocked=t.is_blocked,
        assignee_id=t.assignee_id,
        reviewer_id=t.reviewer_id,
        sprint_id=t.sprint_id,
        project_id=t.project_id,
        project_code=pcode,
        project_name=pname,
    )


async def _visible_project_ids(db: AsyncSession, user_id: UUID, workspace_id: UUID) -> list[UUID]:
    projects = await list_visible_projects(db, user_id, workspace_id)
    return [p.id for p in projects]


async def my_tasks(db: AsyncSession, user_id: UUID, workspace_id: UUID) -> list[TaskCard]:
    ids = await _visible_project_ids(db, user_id, workspace_id)
    if not ids:
        return []
    q = (
        _card_query()
        .where(
            Task.project_id.in_(ids),
            Task.assignee_id == user_id,
            TaskStatus.category != _DONE,
        )
        .order_by(Task.due_at.is_(None), Task.due_at)
    )
    return [_to_card(r) for r in (await db.execute(q)).all()]


async def my_reviews(db: AsyncSession, user_id: UUID, workspace_id: UUID) -> list[TaskCard]:
    ids = await _visible_project_ids(db, user_id, workspace_id)
    if not ids:
        return []
    q = (
        _card_query()
        .where(
            Task.project_id.in_(ids),
            Task.reviewer_id == user_id,
            TaskStatus.category == _REVIEW,
        )
        .order_by(Task.due_at.is_(None), Task.due_at)
    )
    return [_to_card(r) for r in (await db.execute(q)).all()]


async def all_tasks(
    db: AsyncSession,
    user_id: UUID,
    workspace_id: UUID,
    *,
    project_id: UUID | None,
    assignee_id: UUID | None,
    reviewer_id: UUID | None,
    category: str | None,
    priority: str | None,
    limit: int,
    offset: int,
) -> tuple[list[TaskCard], int]:
    ids = await _visible_project_ids(db, user_id, workspace_id)
    if not ids:
        return [], 0
    if project_id is not None:
        if project_id not in ids:
            return [], 0
        ids = [project_id]

    conds = [Task.project_id.in_(ids), Task.deleted_at.is_(None)]
    if assignee_id is not None:
        conds.append(Task.assignee_id == assignee_id)
    if reviewer_id is not None:
        conds.append(Task.reviewer_id == reviewer_id)
    if category is not None:
        conds.append(TaskStatus.category == category)
    if priority is not None:
        conds.append(Task.priority == priority)

    total = await db.scalar(
        select(func.count())
        .select_from(Task)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(*conds)
    )
    q = (
        _card_query()
        .where(*conds)
        .order_by(Task.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_to_card(r) for r in (await db.execute(q)).all()], int(total or 0)


async def _counts_by_project(
    db: AsyncSession, project_ids: list[UUID]
) -> dict[UUID, tuple[int, int, int, int]]:
    now = datetime.now(UTC)
    rows = await db.execute(
        select(
            Task.project_id,
            func.count().filter(TaskStatus.category != _DONE),
            func.count().filter(and_(Task.due_at < now, TaskStatus.category != _DONE)),
            func.count().filter(Task.is_blocked.is_(True)),
            func.count().filter(TaskStatus.category == _REVIEW),
        )
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(Task.project_id.in_(project_ids), Task.deleted_at.is_(None))
        .group_by(Task.project_id)
    )
    return {pid: (o, ov, bl, rv) for pid, o, ov, bl, rv in rows.all()}


async def _active_sprints(
    db: AsyncSession, project_ids: list[UUID]
) -> dict[UUID, tuple[UUID, str]]:
    rows = await db.execute(
        select(Sprint.project_id, Sprint.id, Sprint.name).where(
            Sprint.project_id.in_(project_ids),
            Sprint.status == SprintStatus.ACTIVE.value,
        )
    )
    return {pid: (sid, sname) for pid, sid, sname in rows.all()}


async def _sprint_progress(
    db: AsyncSession, sprint_ids: list[UUID]
) -> dict[UUID, tuple[int, int]]:
    if not sprint_ids:
        return {}
    rows = await db.execute(
        select(
            Task.sprint_id,
            func.count(),
            func.count().filter(TaskStatus.category == _DONE),
        )
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(Task.sprint_id.in_(sprint_ids), Task.deleted_at.is_(None))
        .group_by(Task.sprint_id)
    )
    return {sid: (total, done or 0) for sid, total, done in rows.all()}


async def portfolio(db: AsyncSession, user_id: UUID, workspace_id: UUID) -> PortfolioOut:
    projects = await list_visible_projects(db, user_id, workspace_id)
    ids = [p.id for p in projects]
    if not ids:
        return PortfolioOut(rows=[], totals=PortfolioTotals())

    counts = await _counts_by_project(db, ids)
    actives = await _active_sprints(db, ids)
    progress = await _sprint_progress(db, [sid for sid, _ in actives.values()])

    rows: list[PortfolioRow] = []
    tot_blockers = tot_overdue = active_projects = 0
    for p in projects:
        o, ov, bl, rv = counts.get(p.id, (0, 0, 0, 0))
        tot_blockers += bl
        tot_overdue += ov
        if p.status == "ACTIVE":
            active_projects += 1
        sprint_name = None
        s_done = s_total = 0
        if p.id in actives:
            sid, sprint_name = actives[p.id]
            s_total, s_done = progress.get(sid, (0, 0))
        rows.append(
            PortfolioRow(
                project_id=p.id,
                code=p.code,
                name=p.name,
                health=p.health,
                status=p.status,
                group_name=p.group_name,
                open=o,
                overdue=ov,
                blocked=bl,
                review=rv,
                sprint_name=sprint_name,
                sprint_done=s_done,
                sprint_total=s_total,
            )
        )

    waiting = await db.scalar(
        select(func.count())
        .select_from(Task)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(
            Task.project_id.in_(ids),
            Task.reviewer_id == user_id,
            TaskStatus.category == _REVIEW,
            Task.deleted_at.is_(None),
        )
    )
    return PortfolioOut(
        rows=rows,
        totals=PortfolioTotals(
            active_projects=active_projects,
            blockers=tot_blockers,
            overdue=tot_overdue,
            waiting_my_review=int(waiting or 0),
        ),
    )


async def project_dashboard(
    db: AsyncSession, user_id: UUID, project: Project
) -> ProjectDashboard:
    counts = await _counts_by_project(db, [project.id])
    o, ov, bl, rv = counts.get(project.id, (0, 0, 0, 0))

    current = None
    actives = await _active_sprints(db, [project.id])
    if project.id in actives:
        sid, sname = actives[project.id]
        prog = await _sprint_progress(db, [sid])
        total, done = prog.get(sid, (0, 0))
        goal = await db.scalar(select(Sprint.goal).where(Sprint.id == sid))
        current = SprintBrief(id=sid, name=sname, goal=goal, done=done, total=total)

    waiting = await db.scalar(
        select(func.count())
        .select_from(Task)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(
            Task.project_id == project.id,
            Task.reviewer_id == user_id,
            TaskStatus.category == _REVIEW,
            Task.deleted_at.is_(None),
        )
    )
    return ProjectDashboard(
        project_id=project.id,
        code=project.code,
        name=project.name,
        goal=project.goal,
        health=project.health,
        status=project.status,
        open=o,
        overdue=ov,
        blocked=bl,
        waiting_review=int(waiting or 0),
        current_sprint=current,
    )
