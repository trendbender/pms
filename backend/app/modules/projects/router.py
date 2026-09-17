from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import (
    get_current_user,
    get_workspace_id,
    load_project,
    require_project_permission,
    require_workspace_permission,
)
from app.models.project import Project, ProjectMember
from app.models.task import TaskStatus, TaskType
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.modules.audit.service import record_audit
from app.modules.permissions.constants import Perm
from app.modules.projects import service
from app.modules.projects.schemas import (
    MemberOut,
    MemberUpsert,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    StatusCreate,
    StatusOut,
    StatusUpdate,
    TypeCreate,
    TypeOut,
    TypeUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[Project]:
    return await service.list_visible_projects(db, user.id, workspace_id)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_workspace_permission(Perm.PROJECT_CREATE)),
    db: AsyncSession = Depends(get_db),
) -> Project:
    existing = await db.scalar(
        select(Project.id).where(
            Project.workspace_id == workspace_id, Project.code == body.code
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Project code '{body.code}' already used")

    try:
        project = await service.create_project(
            db,
            workspace_id=workspace_id,
            creator_id=user.id,
            name=body.name,
            code=body.code,
            description=body.description,
            goal=body.goal,
            wip_limit=body.wip_limit,
            group_name=body.group_name,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Project code '{body.code}' already used"
        ) from None

    await record_audit(
        db,
        workspace_id=workspace_id,
        actor_id=user.id,
        action="project.created",
        target_type="project",
        target_id=project.id,
        data={"code": project.code, "name": project.name},
    )
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project: Project = Depends(load_project)) -> Project:
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    _: None = Depends(require_project_permission(Perm.PROJECT_EDIT)),
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await db.get(Project, project_id)
    assert project is not None  # guaranteed by the guard

    if body.owner_id is not None:
        member = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == body.owner_id,
            )
        )
        if member is None:
            raise HTTPException(422, "owner must be a project member")
        project.owner_id = body.owner_id

    for field in (
        "name", "description", "goal", "group_name", "wip_limit", "start_date", "due_date"
    ):
        val = getattr(body, field)
        if val is not None:
            setattr(project, field, val)
    if body.status is not None:
        project.status = body.status.value
    if body.health is not None:
        project.health = body.health.value

    await db.flush()
    return project


@router.post("/{project_id}/archive", response_model=ProjectOut)
async def archive_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.PROJECT_ARCHIVE)),
    db: AsyncSession = Depends(get_db),
) -> Project:
    from datetime import UTC, datetime

    project = await db.get(Project, project_id)
    assert project is not None
    project.status = "ARCHIVED"
    project.archived_at = datetime.now(UTC)
    await record_audit(
        db,
        workspace_id=workspace_id,
        actor_id=user.id,
        action="project.archived",
        target_type="project",
        target_id=project.id,
    )
    await db.flush()
    return project


# --------------------------------------------------------------------------- #
# Members
# --------------------------------------------------------------------------- #


@router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.PROJECT_MEMBERS_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[MemberOut]:
    rows = await db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.name)
    )
    return [
        MemberOut(user_id=u.id, email=u.email, name=u.name, role=pm.role)
        for pm, u in rows.all()
    ]


@router.post(
    "/{project_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED
)
async def add_member(
    project_id: UUID,
    body: MemberUpsert,
    actor: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.PROJECT_MEMBERS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> MemberOut:
    # the target must be a member of this workspace
    in_ws = await db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == body.user_id,
        )
    )
    if in_ws is None:
        raise HTTPException(422, "user is not in this workspace")
    user = await db.get(User, body.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    existing = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == body.user_id,
        )
    )
    if existing is None:
        db.add(
            ProjectMember(project_id=project_id, user_id=body.user_id, role=body.role.value)
        )
        action = "project.member.added"
    else:
        existing.role = body.role.value
        action = "project.member.role_changed"

    await record_audit(
        db,
        workspace_id=workspace_id,
        actor_id=actor.id,
        action=action,
        target_type="project_member",
        target_id=project_id,
        data={"user_id": str(body.user_id), "role": body.role.value},
    )
    await db.flush()
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=body.role.value)


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: UUID,
    user_id: UUID,
    actor: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.PROJECT_MEMBERS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")
    await db.delete(member)
    await record_audit(
        db,
        workspace_id=workspace_id,
        actor_id=actor.id,
        action="project.member.removed",
        target_type="project_member",
        target_id=project_id,
        data={"user_id": str(user_id)},
    )
    await db.flush()
    return None


# --------------------------------------------------------------------------- #
# Workflow config — statuses
# --------------------------------------------------------------------------- #


@router.get("/{project_id}/statuses", response_model=list[StatusOut])
async def list_statuses(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.BOARD_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[TaskStatus]:
    return list(
        (
            await db.scalars(
                select(TaskStatus)
                .where(TaskStatus.project_id == project_id)
                .order_by(TaskStatus.position)
            )
        ).all()
    )


@router.post(
    "/{project_id}/statuses", response_model=StatusOut, status_code=status.HTTP_201_CREATED
)
async def create_status(
    project_id: UUID,
    body: StatusCreate,
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.BOARD_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> TaskStatus:
    pos = body.position
    if pos is None:
        pos = (
            await db.scalar(
                select(TaskStatus.position)
                .where(TaskStatus.project_id == project_id)
                .order_by(TaskStatus.position.desc())
                .limit(1)
            )
            or 0
        ) + 1
    obj = TaskStatus(
        workspace_id=workspace_id,
        project_id=project_id,
        name=body.name,
        category=body.category.value,
        position=pos,
    )
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "status name already exists") from None
    return obj


@router.patch("/{project_id}/statuses/{status_id}", response_model=StatusOut)
async def update_status(
    project_id: UUID,
    status_id: UUID,
    body: StatusUpdate,
    _: None = Depends(require_project_permission(Perm.BOARD_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> TaskStatus:
    obj = await db.get(TaskStatus, status_id)
    if obj is None or obj.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "status not found")
    if body.name is not None:
        obj.name = body.name
    if body.category is not None:
        obj.category = body.category.value
    if body.position is not None:
        obj.position = body.position
    await db.flush()
    return obj


@router.delete(
    "/{project_id}/statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_status(
    project_id: UUID,
    status_id: UUID,
    _: None = Depends(require_project_permission(Perm.BOARD_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    obj = await db.get(TaskStatus, status_id)
    if obj is None or obj.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "status not found")
    try:
        await db.delete(obj)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "status is in use by tasks and cannot be deleted"
        ) from None
    return None


# --------------------------------------------------------------------------- #
# Workflow config — types
# --------------------------------------------------------------------------- #


@router.get("/{project_id}/types", response_model=list[TypeOut])
async def list_types(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.BOARD_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[TaskType]:
    return list(
        (
            await db.scalars(
                select(TaskType)
                .where(TaskType.project_id == project_id)
                .order_by(TaskType.position)
            )
        ).all()
    )


@router.post(
    "/{project_id}/types", response_model=TypeOut, status_code=status.HTTP_201_CREATED
)
async def create_type(
    project_id: UUID,
    body: TypeCreate,
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.BOARD_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> TaskType:
    pos = body.position
    if pos is None:
        pos = (
            await db.scalar(
                select(TaskType.position)
                .where(TaskType.project_id == project_id)
                .order_by(TaskType.position.desc())
                .limit(1)
            )
            or 0
        ) + 1
    obj = TaskType(
        workspace_id=workspace_id, project_id=project_id, name=body.name, position=pos
    )
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "type name already exists") from None
    return obj


@router.patch("/{project_id}/types/{type_id}", response_model=TypeOut)
async def update_type(
    project_id: UUID,
    type_id: UUID,
    body: TypeUpdate,
    _: None = Depends(require_project_permission(Perm.BOARD_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> TaskType:
    obj = await db.get(TaskType, type_id)
    if obj is None or obj.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "type not found")
    if body.name is not None:
        obj.name = body.name
    if body.position is not None:
        obj.position = body.position
    await db.flush()
    return obj


@router.delete("/{project_id}/types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_type(
    project_id: UUID,
    type_id: UUID,
    _: None = Depends(require_project_permission(Perm.BOARD_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    obj = await db.get(TaskType, type_id)
    if obj is None or obj.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "type not found")
    try:
        await db.delete(obj)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "type is in use by tasks and cannot be deleted"
        ) from None
    return None
