from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SprintCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    goal: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class SprintUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    goal: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class SprintComplete(BaseModel):
    # where incomplete (non-DONE) tasks go on completion (spec §29):
    # a target sprint to carry them into, else they return to the backlog.
    next_sprint_id: UUID | None = None


class SprintStats(BaseModel):
    total: int = 0
    done: int = 0
    in_progress: int = 0
    blocked: int = 0
    todo: int = 0


class SprintOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    goal: str | None
    status: str
    start_date: datetime | None
    end_date: datetime | None
    created_at: datetime
    stats: SprintStats

    model_config = {"from_attributes": True}


class SprintCompletionResult(BaseModel):
    sprint: SprintOut
    completed: int
    moved: int
    moved_to: str  # "backlog" or a sprint id
