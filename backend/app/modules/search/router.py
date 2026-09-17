"""Global search over permitted data (spec §45).

MVP uses case-insensitive substring (ILIKE) over task key/title/description and
comment bodies, scoped to the projects the user may view. A Postgres full-text
(tsvector) index is a later optimization.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id
from app.models.comment import Comment
from app.models.task import Task
from app.models.user import User
from app.modules.dashboard.schemas import TaskCard
from app.modules.dashboard.service import _card_query, _to_card, _visible_project_ids

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[TaskCard])
async def search(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[TaskCard]:
    term = q.strip()
    if not term:
        return []
    ids = await _visible_project_ids(db, user.id, workspace_id)
    if not ids:
        return []

    like = f"%{term}%"
    comment_task_ids = select(Comment.task_id).where(
        Comment.body.ilike(like), Comment.deleted_at.is_(None)
    )
    query = (
        _card_query()
        .where(
            Task.project_id.in_(ids),
            or_(
                Task.key.ilike(like),
                Task.title.ilike(like),
                Task.description.ilike(like),
                Task.id.in_(comment_task_ids),
            ),
        )
        .order_by(Task.updated_at.desc())
        .limit(limit)
    )
    return [_to_card(r) for r in (await db.execute(query)).all()]
