"""In-app notifications (spec §44). Email delivery is deferred (needs SMTP config)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def notify(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID | None,
    actor_id: UUID | None,
    kind: str,
    title: str,
    body: str | None = None,
    task_id: UUID | None = None,
    payload: dict | None = None,
) -> None:
    """Create a notification for a recipient. No-op when there is no recipient or
    the recipient is the actor (you don't get pinged for your own action)."""
    if user_id is None or user_id == actor_id:
        return
    db.add(
        Notification(
            workspace_id=workspace_id,
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            task_id=task_id,
            payload=payload,
        )
    )
