from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import (
    get_current_user,
    get_workspace_id,
    require_project_permission,
)
from app.models.sprint import Sprint
from app.models.user import User
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.sprints import service
from app.modules.sprints.schemas import (
    SprintComplete,
    SprintCompletionResult,
    SprintCreate,
    SprintOut,
    SprintUpdate,
)

router = APIRouter(tags=["sprints"])


async def load_sprint(
    sprint_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Sprint:
    sprint = await db.get(Sprint, sprint_id)
    if sprint is None or sprint.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sprint not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, sprint.project_id, Perm.SPRINT_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sprint not found")
    return sprint


async def _require_manage(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, project_id: UUID
) -> None:
    if not await perms.has_project_permission(
        db, user_id, workspace_id, project_id, Perm.SPRINT_MANAGE
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: sprint.manage")


@router.get("/projects/{project_id}/sprints", response_model=list[SprintOut])
async def list_sprints(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.SPRINT_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[SprintOut]:
    return await service.list_sprints(db, project_id)


@router.post(
    "/projects/{project_id}/sprints",
    response_model=SprintOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_sprint(
    project_id: UUID,
    body: SprintCreate,
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.SPRINT_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> SprintOut:
    sprint = Sprint(
        workspace_id=workspace_id,
        project_id=project_id,
        name=body.name,
        goal=body.goal,
        start_date=body.start_date,
        end_date=body.end_date,
        status="PLANNED",
    )
    db.add(sprint)
    await db.flush()
    return service.to_out(sprint, await service.stats(db, sprint.id))


@router.get("/sprints/{sprint_id}", response_model=SprintOut)
async def get_sprint(
    sprint: Sprint = Depends(load_sprint),
    db: AsyncSession = Depends(get_db),
) -> SprintOut:
    return service.to_out(sprint, await service.stats(db, sprint.id))


@router.patch("/sprints/{sprint_id}", response_model=SprintOut)
async def update_sprint(
    body: SprintUpdate,
    sprint: Sprint = Depends(load_sprint),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> SprintOut:
    await _require_manage(db, user.id, workspace_id, sprint.project_id)
    for field in ("name", "goal", "start_date", "end_date"):
        val = getattr(body, field)
        if val is not None:
            setattr(sprint, field, val)
    await db.flush()
    return service.to_out(sprint, await service.stats(db, sprint.id))


@router.post("/sprints/{sprint_id}/start", response_model=SprintOut)
async def start_sprint(
    sprint: Sprint = Depends(load_sprint),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> SprintOut:
    await _require_manage(db, user.id, workspace_id, sprint.project_id)
    try:
        await service.start_sprint(db, sprint)
    except PermissionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return service.to_out(sprint, await service.stats(db, sprint.id))


@router.post("/sprints/{sprint_id}/complete", response_model=SprintCompletionResult)
async def complete_sprint(
    body: SprintComplete,
    sprint: Sprint = Depends(load_sprint),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> SprintCompletionResult:
    await _require_manage(db, user.id, workspace_id, sprint.project_id)
    if sprint.status == "COMPLETED":
        raise HTTPException(status.HTTP_409_CONFLICT, "sprint already completed")

    if body.next_sprint_id is not None:
        target = await db.get(Sprint, body.next_sprint_id)
        if target is None or target.project_id != sprint.project_id:
            raise HTTPException(422, "next_sprint_id must be a sprint in the same project")
        if target.id == sprint.id:
            raise HTTPException(422, "cannot carry tasks into the same sprint")

    completed, moved, moved_to = await service.complete_sprint(
        db, sprint, body.next_sprint_id
    )
    return SprintCompletionResult(
        sprint=service.to_out(sprint, await service.stats(db, sprint.id)),
        completed=completed,
        moved=moved,
        moved_to=moved_to,
    )
