"""Сборка роадмапа: прогресс по волнам, метрики, чем он заблокирован.

Ничего из этого не хранится: волны и пункты живут в инициативах и задачах,
«нужно от владельца и клиента» выводится из заблокированных задач и открытых
вопросов реестра решений. Роадмап хранит только период, согласование, метрики
и ссылки — поэтому он не может разойтись с доской.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import Decision
from app.models.enums import RoadmapStatus, StatusCategory
from app.models.initiative import Initiative
from app.models.project import Project
from app.models.roadmap import Roadmap, RoadmapMetric
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.modules.roadmaps.schemas import (
    MetricOut,
    OpenDecisionOut,
    RoadmapDetail,
    RoadmapOut,
    RoadmapTaskOut,
    WaveOut,
)

_DONE = StatusCategory.DONE.value


def _task_query() -> Select:
    return (
        select(
            Task,
            TaskStatus.name.label("status_name"),
            TaskStatus.category.label("status_category"),
            User.name.label("assignee_name"),
        )
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .outerjoin(User, User.id == Task.assignee_id)
        .where(Task.deleted_at.is_(None))
    )


def _to_task(row) -> RoadmapTaskOut:
    t, status_name, status_category, assignee_name = row
    return RoadmapTaskOut(
        id=t.id,
        key=t.key,
        title=t.title,
        status_name=status_name,
        status_category=status_category,
        priority=t.priority,
        assignee_name=assignee_name,
        due_at=t.due_at,
        completed_at=t.completed_at,
        is_blocked=t.is_blocked,
        blocked_reason=t.blocked_reason,
    )


async def _wave_ids(db: AsyncSession, roadmap_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    rows = await db.execute(
        select(Initiative.roadmap_id, Initiative.id)
        .where(Initiative.roadmap_id.in_(roadmap_ids), Initiative.archived_at.is_(None))
        .order_by(Initiative.due_date.nulls_last(), Initiative.created_at)
    )
    out: dict[UUID, list[UUID]] = {rid: [] for rid in roadmap_ids}
    for roadmap_id, initiative_id in rows.all():
        out[roadmap_id].append(initiative_id)
    return out


async def _task_counts(
    db: AsyncSession, initiative_ids: list[UUID]
) -> dict[UUID, tuple[int, int, int, int]]:
    """(total, done, blocked, overdue) по каждой инициативе-волне."""
    if not initiative_ids:
        return {}
    now = datetime.now(UTC)
    done = func.count(1).filter(TaskStatus.category == _DONE)
    blocked = func.count(1).filter(Task.is_blocked.is_(True), TaskStatus.category != _DONE)
    overdue = func.count(1).filter(
        Task.due_at.is_not(None), Task.due_at < now, TaskStatus.category != _DONE
    )
    rows = await db.execute(
        select(Task.initiative_id, func.count(1), done, blocked, overdue)
        .select_from(Task)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(Task.initiative_id.in_(initiative_ids), Task.deleted_at.is_(None))
        .group_by(Task.initiative_id)
    )
    return {iid: (total, d or 0, b or 0, o or 0) for iid, total, d, b, o in rows.all()}


async def _metric_counts(db: AsyncSession, roadmap_ids: list[UUID]) -> dict[UUID, tuple[int, int]]:
    reached = func.count(1).filter(RoadmapMetric.reached_on.is_not(None))
    rows = await db.execute(
        select(RoadmapMetric.roadmap_id, func.count(1), reached)
        .select_from(RoadmapMetric)
        .where(RoadmapMetric.roadmap_id.in_(roadmap_ids))
        .group_by(RoadmapMetric.roadmap_id)
    )
    return {rid: (total, r or 0) for rid, total, r in rows.all()}


def _to_out(
    r: Roadmap,
    *,
    project: Project | None = None,
    waves: int = 0,
    tasks: tuple[int, int, int, int] = (0, 0, 0, 0),
    metrics: tuple[int, int] = (0, 0),
) -> RoadmapOut:
    total, done, blocked, overdue = tasks
    metric_total, metric_reached = metrics
    return RoadmapOut(
        id=r.id,
        project_id=r.project_id,
        project_code=project.code if project else None,
        project_name=project.name if project else None,
        title=r.title,
        period_start=r.period_start,
        period_end=r.period_end,
        status=r.status,
        goal=r.goal,
        scope_note=r.scope_note,
        agreed_on=r.agreed_on,
        decision_ref=r.decision_ref,
        plan_url=r.plan_url,
        report_url=r.report_url,
        archived_at=r.archived_at,
        created_at=r.created_at,
        wave_count=waves,
        task_count=total,
        done_count=done,
        blocked_count=blocked,
        overdue_count=overdue,
        metric_count=metric_total,
        metric_reached_count=metric_reached,
    )


_WaveMap = dict[UUID, list[UUID]]
_TaskCounts = dict[UUID, tuple[int, int, int, int]]
_MetricCounts = dict[UUID, tuple[int, int]]


async def _rollups(
    db: AsyncSession, roadmaps: list[Roadmap]
) -> tuple[_WaveMap, _TaskCounts, _MetricCounts]:
    ids = [r.id for r in roadmaps]
    if not ids:
        return {}, {}, {}
    waves = await _wave_ids(db, ids)
    counts = await _task_counts(db, [iid for group in waves.values() for iid in group])
    metrics = await _metric_counts(db, ids)
    return waves, counts, metrics


def _sum_counts(
    wave_ids: list[UUID], counts: dict[UUID, tuple[int, int, int, int]]
) -> tuple[int, int, int, int]:
    totals = [0, 0, 0, 0]
    for iid in wave_ids:
        for i, value in enumerate(counts.get(iid, (0, 0, 0, 0))):
            totals[i] += value
    return tuple(totals)  # type: ignore[return-value]


async def list_roadmaps(
    db: AsyncSession, project_id: UUID, *, include_archived: bool = False
) -> list[RoadmapOut]:
    query = select(Roadmap).where(Roadmap.project_id == project_id)
    if not include_archived:
        query = query.where(Roadmap.archived_at.is_(None))
    roadmaps = (await db.scalars(query.order_by(Roadmap.period_start.desc()))).all()
    waves, counts, metrics = await _rollups(db, list(roadmaps))
    project = await db.get(Project, project_id)
    return [
        _to_out(
            r,
            project=project,
            waves=len(waves.get(r.id, [])),
            tasks=_sum_counts(waves.get(r.id, []), counts),
            metrics=metrics.get(r.id, (0, 0)),
        )
        for r in roadmaps
    ]


async def current_roadmap(db: AsyncSession, project_id: UUID) -> Roadmap | None:
    """Роадмап, который показываем по умолчанию: активный, иначе самый свежий."""
    active = await db.scalars(
        select(Roadmap)
        .where(
            Roadmap.project_id == project_id,
            Roadmap.archived_at.is_(None),
            Roadmap.status.in_([RoadmapStatus.ACTIVE.value, RoadmapStatus.AGREED.value]),
        )
        .order_by(Roadmap.period_start.desc())
    )
    found = active.first()
    if found is not None:
        return found
    latest = await db.scalars(
        select(Roadmap)
        .where(Roadmap.project_id == project_id, Roadmap.archived_at.is_(None))
        .order_by(Roadmap.period_start.desc())
    )
    return latest.first()


async def get_detail(db: AsyncSession, roadmap: Roadmap) -> RoadmapDetail:
    waves_by_roadmap, counts, metric_counts = await _rollups(db, [roadmap])
    wave_ids = waves_by_roadmap.get(roadmap.id, [])
    project = await db.get(Project, roadmap.project_id)

    initiatives = (
        await db.scalars(
            select(Initiative)
            .where(Initiative.id.in_(wave_ids))
            .order_by(Initiative.due_date.nulls_last(), Initiative.created_at)
        )
    ).all()
    by_id = {i.id: i for i in initiatives}

    tasks_by_wave: dict[UUID, list[RoadmapTaskOut]] = {iid: [] for iid in wave_ids}
    if wave_ids:
        rows = await db.execute(
            _task_query()
            .where(Task.initiative_id.in_(wave_ids))
            .order_by(Task.due_at.nulls_last(), Task.key)
        )
        for row in rows.all():
            tasks_by_wave[row[0].initiative_id].append(_to_task(row))

    waves = []
    for iid in wave_ids:
        initiative = by_id.get(iid)
        if initiative is None:
            continue
        total, done, _, _ = counts.get(iid, (0, 0, 0, 0))
        waves.append(
            WaveOut(
                id=initiative.id,
                name=initiative.name,
                description=initiative.description,
                due_date=initiative.due_date,
                task_count=total,
                done_count=done,
                tasks=tasks_by_wave.get(iid, []),
            )
        )

    metrics = (
        await db.scalars(
            select(RoadmapMetric)
            .where(RoadmapMetric.roadmap_id == roadmap.id)
            .order_by(RoadmapMetric.position, RoadmapMetric.created_at)
        )
    ).all()

    # Чем роадмап стоит: заблокированные задачи проекта и открытые вопросы реестра.
    waiting_rows = await db.execute(
        _task_query()
        .where(
            Task.project_id == roadmap.project_id,
            Task.is_blocked.is_(True),
            TaskStatus.category != _DONE,
        )
        .order_by(Task.due_at.nulls_last(), Task.key)
    )
    decisions = (
        await db.scalars(
            select(Decision)
            .where(Decision.project_id == roadmap.project_id, Decision.status == "open")
            .order_by(Decision.ref)
        )
    ).all()

    detail = RoadmapDetail(
        **_to_out(
            roadmap,
            project=project,
            waves=len(wave_ids),
            tasks=_sum_counts(wave_ids, counts),
            metrics=metric_counts.get(roadmap.id, (0, 0)),
        ).model_dump()
    )
    detail.waves = waves
    detail.metrics = [MetricOut.model_validate(m) for m in metrics]
    detail.waiting = [_to_task(row) for row in waiting_rows.all()]
    detail.open_decisions = [
        OpenDecisionOut(
            ref=d.ref, registry=d.registry, area_title=d.area_title, question=d.question
        )
        for d in decisions
    ]
    return detail


async def portfolio(db: AsyncSession, project_ids: list[UUID]) -> list[RoadmapOut]:
    """Один таймлайн: по одному текущему роадмапу на каждый видимый проект."""
    if not project_ids:
        return []
    roadmaps = (
        await db.scalars(
            select(Roadmap)
            .where(
                Roadmap.project_id.in_(project_ids),
                Roadmap.archived_at.is_(None),
                Roadmap.status.in_(
                    [
                        RoadmapStatus.AGREED.value,
                        RoadmapStatus.ACTIVE.value,
                        RoadmapStatus.DRAFT.value,
                    ]
                ),
            )
            .order_by(Roadmap.period_start.desc())
        )
    ).all()

    # По проекту берём только один — самый свежий по началу периода.
    picked: dict[UUID, Roadmap] = {}
    for r in roadmaps:
        picked.setdefault(r.project_id, r)
    chosen = list(picked.values())
    waves, counts, metrics = await _rollups(db, chosen)
    projects = {
        p.id: p
        for p in (
            await db.scalars(select(Project).where(Project.id.in_([r.project_id for r in chosen])))
        ).all()
    }
    out = [
        _to_out(
            r,
            project=projects.get(r.project_id),
            waves=len(waves.get(r.id, [])),
            tasks=_sum_counts(waves.get(r.id, []), counts),
            metrics=metrics.get(r.id, (0, 0)),
        )
        for r in chosen
    ]
    out.sort(key=lambda r: (r.period_start, r.project_code or ""))
    return out
