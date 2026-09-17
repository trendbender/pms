from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id, load_project
from app.models.project import Project
from app.models.user import User
from app.modules.dashboard import service
from app.modules.dashboard.schemas import (
    PagedTasks,
    PortfolioOut,
    ProjectDashboard,
    TaskCard,
)

router = APIRouter(tags=["dashboard"])


@router.get("/me/tasks", response_model=list[TaskCard])
async def my_tasks(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[TaskCard]:
    return await service.my_tasks(db, user.id, workspace_id)


@router.get("/me/reviews", response_model=list[TaskCard])
async def my_reviews(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[TaskCard]:
    return await service.my_reviews(db, user.id, workspace_id)


@router.get("/tasks", response_model=PagedTasks)
async def all_tasks(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
    project_id: UUID | None = Query(default=None),
    assignee_id: UUID | None = Query(default=None),
    reviewer_id: UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PagedTasks:
    items, total = await service.all_tasks(
        db,
        user.id,
        workspace_id,
        project_id=project_id,
        assignee_id=assignee_id,
        reviewer_id=reviewer_id,
        category=category,
        priority=priority,
        limit=limit,
        offset=offset,
    )
    return PagedTasks(items=items, total=total, limit=limit, offset=offset)


@router.get("/portfolio", response_model=PortfolioOut)
async def portfolio(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> PortfolioOut:
    return await service.portfolio(db, user.id, workspace_id)


@router.get("/projects/{project_id}/dashboard", response_model=ProjectDashboard)
async def project_dashboard(
    project: Project = Depends(load_project),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectDashboard:
    return await service.project_dashboard(db, user.id, project)
