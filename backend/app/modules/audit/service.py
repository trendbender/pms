"""Helpers to append to the activity and audit logs. Logs are append-only."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import ActivityLog, AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_id: UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: UUID | None = None,
    data: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            data=data,
        )
    )


async def record_activity(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    task_id: UUID | None,
    actor_id: UUID | None,
    action: str,
    data: dict | None = None,
) -> None:
    db.add(
        ActivityLog(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_id=actor_id,
            action=action,
            data=data,
        )
    )
