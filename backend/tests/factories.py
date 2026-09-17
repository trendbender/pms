"""Small helpers to build workspace + users directly in the DB for tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.enums import SystemRole
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


async def make_workspace(session: AsyncSession, name: str = "WS") -> Workspace:
    ws = Workspace(name=name)
    session.add(ws)
    await session.flush()
    return ws


async def make_user(
    session: AsyncSession,
    workspace: Workspace,
    email: str,
    role: SystemRole = SystemRole.MEMBER,
    password: str = "password123",
    name: str | None = None,
) -> User:
    user = User(email=email.lower(), name=name or email, password_hash=hash_password(password))
    session.add(user)
    await session.flush()
    session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, system_role=role.value)
    )
    await session.flush()
    return user
