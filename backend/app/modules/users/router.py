from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id, require_workspace_permission
from app.core.security import hash_password
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.modules.audit.service import record_audit
from app.modules.permissions.constants import Perm
from app.modules.users.schemas import (
    InviteUserRequest,
    UpdateMeRequest,
    UpdateUserRequest,
    UserOut,
)

router = APIRouter(prefix="/users", tags=["users"])


async def _role_map(db: AsyncSession, workspace_id: UUID) -> dict[UUID, str]:
    rows = await db.execute(
        select(WorkspaceMember.user_id, WorkspaceMember.system_role).where(
            WorkspaceMember.workspace_id == workspace_id
        )
    )
    return {uid: role for uid, role in rows.all()}


@router.get("", response_model=list[UserOut])
async def list_users(
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_workspace_permission(Perm.WORKSPACE_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    roles = await _role_map(db, workspace_id)
    users = (
        await db.scalars(select(User).where(User.id.in_(roles.keys())).order_by(User.name))
    ).all()
    return [
        UserOut(
            id=u.id,
            email=u.email,
            name=u.name,
            is_active=u.is_active,
            is_suspended=u.is_suspended,
            language=u.language,
            system_role=roles.get(u.id),
        )
        for u in users
    ]


@router.post("/invite", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteUserRequest,
    actor: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_workspace_permission(Perm.WORKSPACE_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    email = body.email.lower()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User with this email already exists")

    user = User(
        email=email,
        name=body.name,
        password_hash=hash_password(body.initial_password) if body.initial_password else None,
    )
    db.add(user)
    await db.flush()

    db.add(
        WorkspaceMember(
            workspace_id=workspace_id, user_id=user.id, system_role=body.system_role.value
        )
    )
    await record_audit(
        db,
        workspace_id=workspace_id,
        actor_id=actor.id,
        action="user.invited",
        target_type="user",
        target_id=user.id,
        data={"email": email, "system_role": body.system_role.value},
    )
    await db.flush()
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        is_suspended=user.is_suspended,
        language=user.language,
        system_role=body.system_role.value,
    )


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateMeRequest,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """Any authenticated user updates their own profile (name, UI language)."""
    if body.name is not None:
        user.name = body.name
    if body.language is not None:
        user.language = body.language
    await db.flush()
    role = await db.scalar(
        select(WorkspaceMember.system_role).where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        is_suspended=user.is_suspended,
        language=user.language,
        system_role=role,
    )


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: UUID,
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_workspace_permission(Perm.WORKSPACE_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    roles = await _role_map(db, workspace_id)
    if user_id not in roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in workspace")
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return UserOut(
        id=u.id,
        email=u.email,
        name=u.name,
        is_active=u.is_active,
        is_suspended=u.is_suspended,
        system_role=roles.get(u.id),
    )


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    actor: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_workspace_permission(Perm.WORKSPACE_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    membership = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in workspace")
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if body.name is not None:
        u.name = body.name

    if body.is_suspended is not None and body.is_suspended != u.is_suspended:
        u.is_suspended = body.is_suspended
        await record_audit(
            db,
            workspace_id=workspace_id,
            actor_id=actor.id,
            action="user.suspended" if body.is_suspended else "user.reinstated",
            target_type="user",
            target_id=u.id,
        )

    if body.system_role is not None and body.system_role.value != membership.system_role:
        old = membership.system_role
        membership.system_role = body.system_role.value
        await record_audit(
            db,
            workspace_id=workspace_id,
            actor_id=actor.id,
            action="role.changed",
            target_type="user",
            target_id=u.id,
            data={"from": old, "to": body.system_role.value},
        )

    await db.flush()
    return UserOut(
        id=u.id,
        email=u.email,
        name=u.name,
        is_active=u.is_active,
        is_suspended=u.is_suspended,
        language=u.language,
        system_role=membership.system_role,
    )
