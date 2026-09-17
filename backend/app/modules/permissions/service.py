"""Authorization service — resolves a user's effective permissions.

Two scopes:
  * workspace-wide (from workspace_members.system_role)
  * per-project (from project_members.role)

A workspace Owner/Admin implicitly has full access to every project even
without an explicit project_members row.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole, SystemRole
from app.models.project import ProjectMember
from app.models.workspace import WorkspaceMember
from app.modules.permissions.constants import (
    PROJECT_ROLE_PERMS,
    SYSTEM_ROLE_PERMS,
    Perm,
)

_SUPERUSER_ROLES = {SystemRole.OWNER, SystemRole.ADMIN}


async def get_system_role(
    db: AsyncSession, user_id: UUID, workspace_id: UUID
) -> SystemRole | None:
    row = await db.scalar(
        select(WorkspaceMember.system_role).where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    return SystemRole(row) if row else None


async def get_project_role(
    db: AsyncSession, user_id: UUID, project_id: UUID
) -> ProjectRole | None:
    row = await db.scalar(
        select(ProjectMember.role).where(
            ProjectMember.user_id == user_id,
            ProjectMember.project_id == project_id,
        )
    )
    return ProjectRole(row) if row else None


async def workspace_permissions(
    db: AsyncSession, user_id: UUID, workspace_id: UUID
) -> frozenset[Perm]:
    role = await get_system_role(db, user_id, workspace_id)
    if role is None:
        return frozenset()
    return SYSTEM_ROLE_PERMS.get(role, frozenset())


async def project_permissions(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, project_id: UUID
) -> frozenset[Perm]:
    """Effective permissions for a user on a specific project."""
    sys_role = await get_system_role(db, user_id, workspace_id)
    if sys_role in _SUPERUSER_ROLES:
        return PROJECT_ROLE_PERMS[ProjectRole.OWNER] | SYSTEM_ROLE_PERMS[sys_role]

    proj_role = await get_project_role(db, user_id, project_id)
    if proj_role is None:
        # no project access at all — user must not see the project (spec §7)
        return frozenset()
    return PROJECT_ROLE_PERMS.get(proj_role, frozenset())


async def has_project_permission(
    db: AsyncSession,
    user_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    perm: Perm,
) -> bool:
    return perm in await project_permissions(db, user_id, workspace_id, project_id)


async def has_workspace_permission(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, perm: Perm
) -> bool:
    return perm in await workspace_permissions(db, user_id, workspace_id)
