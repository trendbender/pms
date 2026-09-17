"""Shared FastAPI dependencies: current user, workspace context, permission guards."""

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import ACCESS_TOKEN, decode_token
from app.models.project import Project
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    payload = decode_token(creds.credentials)
    if not payload or payload.get("type") != ACCESS_TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject") from None

    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.is_suspended:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return user


async def get_workspace_id(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """Resolve the current workspace.

    MVP is single-workspace, so we pick the user's (only) workspace membership.
    The token may also carry `ws`; kept simple here.
    """
    ws_id = await db.scalar(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id).limit(1)
    )
    if ws_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User has no workspace membership")
    return ws_id


def require_workspace_permission(perm: Perm):
    """Dependency factory: require a workspace-level permission."""

    async def _dep(
        user: User = Depends(get_current_user),
        workspace_id: UUID = Depends(get_workspace_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if not await perms.has_workspace_permission(db, user.id, workspace_id, perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")

    return _dep


async def load_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Fetch a project in the current workspace the user is allowed to *see*.

    Enforces spec §7: no project access -> the project must not be visible
    (404, not 403, so its existence isn't leaked).
    """
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, project_id, Perm.PROJECT_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def require_project_permission(perm: Perm):
    """Dependency factory: require a per-project permission (project_id from path)."""

    async def _dep(
        project_id: UUID,
        user: User = Depends(get_current_user),
        workspace_id: UUID = Depends(get_workspace_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        # existence + visibility first, so missing view rights read as 404
        project = await db.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        if not await perms.has_project_permission(db, user.id, workspace_id, project_id, perm):
            # if the user can't even view it, hide it; otherwise say forbidden
            can_view = await perms.has_project_permission(
                db, user.id, workspace_id, project_id, Perm.PROJECT_VIEW
            )
            if not can_view:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")

    return _dep
