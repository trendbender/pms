from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id
from app.models.attachment import Attachment
from app.models.task import Task
from app.models.user import User
from app.modules.attachments import service
from app.modules.attachments.schemas import AttachmentOut
from app.modules.audit.service import record_activity
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.tasks.router import load_task

router = APIRouter(tags=["attachments"])


async def _require(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, project_id: UUID, perm: Perm
) -> None:
    if not await perms.has_project_permission(db, user_id, workspace_id, project_id, perm):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")


async def _load_attachment(
    attachment_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Attachment:
    att = await db.get(Attachment, attachment_id)
    if att is None or att.workspace_id != workspace_id or att.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    task = await db.get(Task, att.task_id)
    if task is None or not await perms.has_project_permission(
        db, user.id, workspace_id, task.project_id, Perm.PROJECT_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return att


@router.get("/tasks/{task_id}/attachments", response_model=list[AttachmentOut])
async def list_attachments(
    task: Task = Depends(load_task),
    db: AsyncSession = Depends(get_db),
) -> list[Attachment]:
    return list(
        (
            await db.scalars(
                select(Attachment)
                .where(Attachment.task_id == task.id, Attachment.deleted_at.is_(None))
                .order_by(Attachment.created_at)
            )
        ).all()
    )


@router.post(
    "/tasks/{task_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    file: UploadFile = File(...),
    task: Task = Depends(load_task),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Attachment:
    await _require(db, user.id, workspace_id, task.project_id, Perm.ATTACHMENT_UPLOAD)

    data = await file.read()
    if not data:
        raise HTTPException(422, "empty file")
    limit = settings.max_attachment_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(413, f"file exceeds {settings.max_attachment_mb} MB limit")

    filename = (file.filename or "file").strip()[:500]
    attachment_id = uuid4()
    storage_key = service.build_storage_key(workspace_id, task.id, attachment_id, filename)
    service.write_file(storage_key, data)

    att = Attachment(
        id=attachment_id,
        workspace_id=workspace_id,
        task_id=task.id,
        comment_id=None,
        uploaded_by=user.id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        storage_key=storage_key,
    )
    db.add(att)
    await record_activity(
        db,
        workspace_id=workspace_id,
        task_id=task.id,
        actor_id=user.id,
        action="attachment.added",
        data={"filename": filename},
    )
    await db.flush()
    return att


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    att: Attachment = Depends(_load_attachment),
) -> FileResponse:
    path = service.absolute_path(att.storage_key)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File is missing on storage")
    return FileResponse(path, media_type=att.content_type, filename=att.filename)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    att: Attachment = Depends(_load_attachment),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await db.get(Task, att.task_id)
    if task is None:  # _load_attachment already validated it; guard for the type checker
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    await _require(db, user.id, workspace_id, task.project_id, Perm.ATTACHMENT_DELETE)
    att.deleted_at = datetime.now(UTC)
    service.delete_file(att.storage_key)
    await record_activity(
        db,
        workspace_id=workspace_id,
        task_id=att.task_id,
        actor_id=user.id,
        action="attachment.deleted",
        data={"filename": att.filename},
    )
    await db.flush()
    return None
