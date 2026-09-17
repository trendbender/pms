"""Project domain services: creation (with default workflow seeding) and listing."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    DEFAULT_STATUSES,
    DEFAULT_TYPES,
    ProjectRole,
    SystemRole,
)
from app.models.project import Project, ProjectMember
from app.models.task import TaskStatus, TaskType
from app.models.workspace import WorkspaceMember


async def seed_project_workflow(db: AsyncSession, project: Project) -> None:
    """Create the default configurable statuses and types for a new project."""
    for pos, (name, category) in enumerate(DEFAULT_STATUSES):
        db.add(
            TaskStatus(
                workspace_id=project.workspace_id,
                project_id=project.id,
                name=name,
                category=category.value,
                position=pos,
            )
        )
    for pos, name in enumerate(DEFAULT_TYPES):
        db.add(
            TaskType(
                workspace_id=project.workspace_id,
                project_id=project.id,
                name=name,
                position=pos,
            )
        )


async def create_project(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    creator_id: UUID,
    name: str,
    code: str,
    description: str | None,
    goal: str | None,
    wip_limit: int | None,
    group_name: str | None = None,
) -> Project:
    project = Project(
        workspace_id=workspace_id,
        name=name,
        code=code,
        description=description,
        goal=goal,
        group_name=group_name,
        wip_limit=wip_limit,
        owner_id=creator_id,
        status="DRAFT",
        health="ON_TRACK",
    )
    db.add(project)
    await db.flush()

    # creator becomes the project Owner (unless they're a workspace superuser,
    # in which case they already have implicit access — but an explicit row keeps
    # listing simple and lets them be shown as owner)
    db.add(
        ProjectMember(project_id=project.id, user_id=creator_id, role=ProjectRole.OWNER.value)
    )
    await seed_project_workflow(db, project)
    await db.flush()
    return project


async def list_visible_projects(
    db: AsyncSession, user_id: UUID, workspace_id: UUID
) -> list[Project]:
    """Projects the user may see: all (workspace Owner/Admin) or those they belong to."""
    sys_role = await db.scalar(
        select(WorkspaceMember.system_role).where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    stmt = select(Project).where(Project.workspace_id == workspace_id)
    if sys_role not in (SystemRole.OWNER.value, SystemRole.ADMIN.value):
        member_project_ids = select(ProjectMember.project_id).where(
            ProjectMember.user_id == user_id
        )
        stmt = stmt.where(Project.id.in_(member_project_ids))
    stmt = stmt.order_by(Project.created_at.desc())
    return list((await db.scalars(stmt)).all())
