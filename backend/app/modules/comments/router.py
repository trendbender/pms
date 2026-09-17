from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id
from app.models.comment import Comment
from app.models.task import Task
from app.models.user import User
from app.modules.audit.service import record_activity
from app.modules.comments.schemas import CommentCreate, CommentOut, CommentUpdate
from app.modules.notifications.service import notify
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.tasks.router import load_task

router = APIRouter(tags=["comments"])


async def _load_comment(
    comment_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Comment:
    comment = await db.get(Comment, comment_id)
    if comment is None or comment.workspace_id != workspace_id or comment.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    # visibility follows the parent task's project
    task = await db.get(Task, comment.task_id)
    if task is None or not await perms.has_project_permission(
        db, user.id, workspace_id, task.project_id, Perm.PROJECT_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    return comment


@router.get("/tasks/{task_id}/comments", response_model=list[CommentOut])
async def list_comments(
    task: Task = Depends(load_task),
    db: AsyncSession = Depends(get_db),
) -> list[Comment]:
    return list(
        (
            await db.scalars(
                select(Comment)
                .where(Comment.task_id == task.id, Comment.deleted_at.is_(None))
                .order_by(Comment.created_at)
            )
        ).all()
    )


@router.post(
    "/tasks/{task_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED
)
async def create_comment(
    body: CommentCreate,
    task: Task = Depends(load_task),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Comment:
    if not await perms.has_project_permission(
        db, user.id, workspace_id, task.project_id, Perm.COMMENT_CREATE
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: comment.create")
    comment = Comment(
        workspace_id=workspace_id, task_id=task.id, author_id=user.id, body=body.body
    )
    db.add(comment)
    await db.flush()
    await record_activity(
        db,
        workspace_id=workspace_id,
        task_id=task.id,
        actor_id=user.id,
        action="comment.created",
        data={"comment_id": str(comment.id)},
    )
    # ping the people on the task (not the commenter)
    label = f"{task.key}: {task.title}"
    for recipient in {task.assignee_id, task.reviewer_id}:
        await notify(
            db, workspace_id=workspace_id, user_id=recipient, actor_id=user.id,
            kind="comment", title=label, body=body.body[:200], task_id=task.id,
        )
    return comment


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def update_comment(
    body: CommentUpdate,
    comment: Comment = Depends(_load_comment),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Comment:
    task = await db.get(Task, comment.task_id)
    assert task is not None
    is_author = comment.author_id == user.id
    can_edit = await perms.has_project_permission(
        db, user.id, workspace_id, task.project_id, Perm.COMMENT_EDIT
    )
    if not (is_author and can_edit):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Can only edit your own comment")
    comment.body = body.body
    comment.edited_at = datetime.now(UTC)
    await db.flush()
    return comment


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment: Comment = Depends(_load_comment),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await db.get(Task, comment.task_id)
    assert task is not None
    is_author = comment.author_id == user.id
    can_delete_any = await perms.has_project_permission(
        db, user.id, workspace_id, task.project_id, Perm.COMMENT_DELETE
    )
    can_create = await perms.has_project_permission(
        db, user.id, workspace_id, task.project_id, Perm.COMMENT_CREATE
    )
    if not (can_delete_any or (is_author and can_create)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to delete this comment")
    comment.deleted_at = datetime.now(UTC)
    await db.flush()
    return None
