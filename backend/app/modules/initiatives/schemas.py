from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InitiativeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class InitiativeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class InitiativeOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: str | None
    task_count: int = 0
    done_count: int = 0
    archived_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
