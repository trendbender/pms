from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id
from app.models.notification import Notification
from app.models.user import User
from app.modules.notifications.schemas import NotificationOut, UnreadCount

router = APIRouter(tags=["notifications"])


@router.get("/me/notifications", response_model=list[NotificationOut])
async def list_notifications(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
    unread: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Notification]:
    q = select(Notification).where(
        Notification.user_id == user.id, Notification.workspace_id == workspace_id
    )
    if unread:
        q = q.where(Notification.read_at.is_(None))
    q = q.order_by(Notification.created_at.desc()).limit(limit)
    return list((await db.scalars(q)).all())


@router.get("/me/notifications/count", response_model=UnreadCount)
async def unread_count(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> UnreadCount:
    n = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.workspace_id == workspace_id,
            Notification.read_at.is_(None),
        )
    )
    return UnreadCount(unread=int(n or 0))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Notification:
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
    await db.flush()
    return n


@router.post("/me/notifications/read-all", response_model=UnreadCount)
async def mark_all_read(
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> UnreadCount:
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.workspace_id == workspace_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.flush()
    return UnreadCount(unread=0)
