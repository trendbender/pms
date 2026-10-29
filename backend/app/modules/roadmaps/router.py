from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import DbSession
from app.core.deps import (
    get_current_user,
    get_workspace_id,
    require_project_permission,
)
from app.models.roadmap import Roadmap, RoadmapMetric
from app.models.user import User
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.projects.service import list_visible_projects
from app.modules.roadmaps import service
from app.modules.roadmaps.schemas import (
    MetricCreate,
    MetricOut,
    MetricUpdate,
    RoadmapCreate,
    RoadmapDetail,
    RoadmapOut,
    RoadmapUpdate,
)

router = APIRouter(tags=["roadmaps"])


async def load_roadmap(
    roadmap_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> Roadmap:
    obj = await db.get(Roadmap, roadmap_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roadmap not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, obj.project_id, Perm.ROADMAP_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roadmap not found")
    return obj


async def load_metric(
    metric_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> RoadmapMetric:
    obj = await db.get(RoadmapMetric, metric_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Metric not found")
    roadmap = await db.get(Roadmap, obj.roadmap_id)
    if roadmap is None or not await perms.has_project_permission(
        db, user.id, workspace_id, roadmap.project_id, Perm.ROADMAP_MANAGE
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Metric not found")
    return obj


async def _require_manage(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, project_id: UUID
) -> None:
    if not await perms.has_project_permission(
        db, user_id, workspace_id, project_id, Perm.ROADMAP_MANAGE
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: roadmap.manage")


@router.get("/roadmap", response_model=list[RoadmapOut])
async def portfolio_roadmap(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> list[RoadmapOut]:
    """Текущие роадмапы всех видимых проектов — один таймлайн портфеля."""
    projects = await list_visible_projects(db, user.id, workspace_id)
    return await service.portfolio(db, [p.id for p in projects])


@router.get("/projects/{project_id}/roadmaps", response_model=list[RoadmapOut])
async def list_roadmaps(
    project_id: UUID,
    include_archived: bool = False,
    _: None = Depends(require_project_permission(Perm.ROADMAP_VIEW)),
    db: AsyncSession = DbSession,
) -> list[RoadmapOut]:
    return await service.list_roadmaps(db, project_id, include_archived=include_archived)


@router.get("/projects/{project_id}/roadmap", response_model=RoadmapDetail)
async def current_roadmap(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.ROADMAP_VIEW)),
    db: AsyncSession = DbSession,
) -> RoadmapDetail:
    """Роадмап, который проект показывает по умолчанию: активный, иначе свежайший."""
    roadmap = await service.current_roadmap(db, project_id)
    if roadmap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roadmap not found")
    return await service.get_detail(db, roadmap)


@router.post(
    "/projects/{project_id}/roadmaps",
    response_model=RoadmapOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_roadmap(
    project_id: UUID,
    body: RoadmapCreate,
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.ROADMAP_MANAGE)),
    db: AsyncSession = DbSession,
) -> RoadmapOut:
    if body.period_end is not None and body.period_end < body.period_start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "period_end is before period_start")
    obj = Roadmap(
        workspace_id=workspace_id,
        project_id=project_id,
        **body.model_dump(),
    )
    db.add(obj)
    await db.flush()
    return await service.get_detail(db, obj)


@router.get("/roadmaps/{roadmap_id}", response_model=RoadmapDetail)
async def get_roadmap(
    roadmap: Roadmap = Depends(load_roadmap),
    db: AsyncSession = DbSession,
) -> RoadmapDetail:
    return await service.get_detail(db, roadmap)


@router.patch("/roadmaps/{roadmap_id}", response_model=RoadmapDetail)
async def update_roadmap(
    body: RoadmapUpdate,
    roadmap: Roadmap = Depends(load_roadmap),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> RoadmapDetail:
    await _require_manage(db, user.id, workspace_id, roadmap.project_id)
    data = body.model_dump(exclude_unset=True)
    start = data.get("period_start", roadmap.period_start)
    end = data.get("period_end", roadmap.period_end)
    if end is not None and start is not None and end < start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "period_end is before period_start")
    for field, value in data.items():
        setattr(roadmap, field, value)
    await db.flush()
    return await service.get_detail(db, roadmap)


@router.post("/roadmaps/{roadmap_id}/archive", response_model=RoadmapOut)
async def archive_roadmap(
    roadmap: Roadmap = Depends(load_roadmap),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> RoadmapOut:
    await _require_manage(db, user.id, workspace_id, roadmap.project_id)
    roadmap.archived_at = datetime.now(UTC)
    await db.flush()
    return await service.get_detail(db, roadmap)


@router.delete("/roadmaps/{roadmap_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_roadmap(
    roadmap: Roadmap = Depends(load_roadmap),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> None:
    await _require_manage(db, user.id, workspace_id, roadmap.project_id)
    # волны остаются инициативами: FK очищает только ссылку на роадмап
    await db.delete(roadmap)
    await db.flush()
    return None


@router.get("/roadmaps/{roadmap_id}/metrics", response_model=list[MetricOut])
async def list_metrics(
    roadmap: Roadmap = Depends(load_roadmap),
    db: AsyncSession = DbSession,
) -> list[MetricOut]:
    rows = await db.scalars(
        select(RoadmapMetric)
        .where(RoadmapMetric.roadmap_id == roadmap.id)
        .order_by(RoadmapMetric.position, RoadmapMetric.created_at)
    )
    return [MetricOut.model_validate(m) for m in rows.all()]


@router.post(
    "/roadmaps/{roadmap_id}/metrics",
    response_model=MetricOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_metric(
    body: MetricCreate,
    roadmap: Roadmap = Depends(load_roadmap),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> MetricOut:
    await _require_manage(db, user.id, workspace_id, roadmap.project_id)
    data = body.model_dump()
    if data.get("position") is None:
        last = await db.scalar(
            select(func.max(RoadmapMetric.position)).where(RoadmapMetric.roadmap_id == roadmap.id)
        )
        data["position"] = (last or 0) + 10
    obj = RoadmapMetric(workspace_id=workspace_id, roadmap_id=roadmap.id, **data)
    db.add(obj)
    await db.flush()
    return MetricOut.model_validate(obj)


@router.patch("/roadmap-metrics/{metric_id}", response_model=MetricOut)
async def update_metric(
    body: MetricUpdate,
    metric: RoadmapMetric = Depends(load_metric),
    db: AsyncSession = DbSession,
) -> MetricOut:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(metric, field, value)
    await db.flush()
    return MetricOut.model_validate(metric)


@router.delete("/roadmap-metrics/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_metric(
    metric: RoadmapMetric = Depends(load_metric),
    db: AsyncSession = DbSession,
) -> None:
    await db.delete(metric)
    await db.flush()
    return None
