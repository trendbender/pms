from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    id: UUID
    task_id: UUID
    comment_id: UUID | None
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
