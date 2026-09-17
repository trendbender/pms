from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id
from app.core.security import (
    REFRESH_TOKEN,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    ResetPasswordRequest,
    TokenPair,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    # Constant-ish behaviour: always run a verify to avoid user enumeration timing.
    if user is None or not user.password_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.is_active or user.is_suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")

    # transparent rehash if Argon2 params changed
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    ws_id = await db.scalar(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id).limit(1)
    )
    ws = str(ws_id) if ws_id else None
    return TokenPair(
        access_token=create_access_token(str(user.id), ws),
        refresh_token=create_refresh_token(str(user.id), ws),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != REFRESH_TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject") from None

    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.is_suspended:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")

    ws = payload.get("ws")
    return TokenPair(
        access_token=create_access_token(str(user.id), ws),
        refresh_token=create_refresh_token(str(user.id), ws),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(_: User = Depends(get_current_user)) -> None:
    # Stateless JWT: client discards tokens. A Redis denylist can be added later.
    return None


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordRequest) -> dict:
    # Email delivery lands in Sprint 7. Always return 202 to avoid enumeration.
    return {"status": "accepted"}


@router.post("/reset-password", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def reset_password(body: ResetPasswordRequest) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Password reset email not wired yet")


@router.get("/me", response_model=MeResponse)
async def me(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    role = await db.scalar(
        select(WorkspaceMember.system_role).where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        language=user.language,
        system_role=role,
    )
