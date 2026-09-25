from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import (
    get_current_user,
    get_workspace_id,
    require_project_permission,
)
from app.models.initiative import Initiative
from app.models.user import User
from app.modules.initiatives import service
from app.modules.initiatives.schemas import (
    InitiativeCreate,
    InitiativeOut,
    InitiativeUpdate,
)
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.tasks import service as task_service
from app.modules.tasks.schemas import TaskOut

router = APIRouter(tags=["initiatives"])


async def load_initiative(
    initiative_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Initiative:
    obj = await db.get(Initiative, initiative_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Initiative not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, obj.project_id, Perm.PROJECT_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Initiative not found")
    return obj


async def _require_edit(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, project_id: UUID
) -> None:
    if not await perms.has_project_permission(
        db, user_id, workspace_id, project_id, Perm.PROJECT_EDIT
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: project.edit")


@router.get("/projects/{project_id}/initiatives", response_model=list[InitiativeOut])
async def list_initiatives(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.PROJECT_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[InitiativeOut]:
    return await service.list_initiatives(db, project_id)


@router.post(
    "/projects/{project_id}/initiatives",
    response_model=InitiativeOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_initiative(
    project_id: UUID,
    body: InitiativeCreate,
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.PROJECT_EDIT)),
    db: AsyncSession = Depends(get_db),
) -> InitiativeOut:
    obj = Initiative(
        workspace_id=workspace_id,
        project_id=project_id,
        name=body.name,
        description=body.description,
        due_date=body.due_date,
    )
    db.add(obj)
    await db.flush()
    return service.to_out(obj)


@router.get("/initiatives/{initiative_id}", response_model=InitiativeOut)
async def get_initiative(
    initiative: Initiative = Depends(load_initiative),
    db: AsyncSession = Depends(get_db),
) -> InitiativeOut:
    return await service.get_out(db, initiative)


@router.get("/initiatives/{initiative_id}/tasks", response_model=list[TaskOut])
async def initiative_tasks(
    initiative: Initiative = Depends(load_initiative),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    return await task_service.list_project_tasks(
        db, project_id=initiative.project_id, initiative_id=initiative.id
    )


@router.patch("/initiatives/{initiative_id}", response_model=InitiativeOut)
async def update_initiative(
    body: InitiativeUpdate,
    initiative: Initiative = Depends(load_initiative),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> InitiativeOut:
    await _require_edit(db, user.id, workspace_id, initiative.project_id)
    if body.name is not None:
        initiative.name = body.name
    if body.description is not None:
        initiative.description = body.description
    if "due_date" in body.model_fields_set:
        initiative.due_date = body.due_date
    await db.flush()
    return await service.get_out(db, initiative)


@router.delete("/initiatives/{initiative_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative(
    initiative: Initiative = Depends(load_initiative),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_edit(db, user.id, workspace_id, initiative.project_id)
    # tasks keep existing; their initiative_id is cleared by the FK (ON DELETE SET NULL)
    await db.delete(initiative)
    await db.flush()
    return None
