from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class CommentOut(BaseModel):
    id: UUID
    task_id: UUID
    author_id: UUID | None
    body: str
    edited_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
