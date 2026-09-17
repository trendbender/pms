from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str | None
    task_id: UUID | None
    payload: dict | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UnreadCount(BaseModel):
    unread: int
