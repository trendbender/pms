from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import Priority


class TaskCreate(BaseModel):
    """Fast-path create (spec §18): only a title is required; the rest is optional
    and can be filled in later (progressive disclosure)."""

    project_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None

    type_id: UUID | None = None
    status_id: UUID | None = None
    priority: Priority = Priority.MEDIUM

    assignee_id: UUID | None = None
    reviewer_id: UUID | None = None

    parent_id: UUID | None = None
    initiative_id: UUID | None = None
    sprint_id: UUID | None = None

    acceptance_criteria: str | None = None
    definition_of_done: str | None = None
    story_points: int | None = Field(default=None, ge=0, le=100)

    start_at: datetime | None = None
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    type_id: UUID | None = None
    priority: Priority | None = None
    assignee_id: UUID | None = None
    reviewer_id: UUID | None = None
    parent_id: UUID | None = None
    initiative_id: UUID | None = None
    sprint_id: UUID | None = None
    acceptance_criteria: str | None = None
    definition_of_done: str | None = None
    story_points: int | None = Field(default=None, ge=0, le=100)
    start_at: datetime | None = None
    due_at: datetime | None = None

    # sentinels let a caller clear an optional FK (send null) — Pydantic can't
    # distinguish "absent" from "null", so unset fields are ignored in the router
    # via model_dump(exclude_unset=True).


class StatusChange(BaseModel):
    status_id: UUID
    # required by convention when moving into a BLOCKED-category status (Rule 8)
    reason: str | None = None


class TaskOut(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID

    number: int
    key: str

    parent_id: UUID | None
    initiative_id: UUID | None

    title: str
    description: str | None

    type_id: UUID
    type_name: str | None
    status_id: UUID
    status_name: str | None
    status_category: str | None
    priority: str

    assignee_id: UUID | None
    reviewer_id: UUID | None
    reporter_id: UUID | None
    sprint_id: UUID | None

    acceptance_criteria: str | None
    definition_of_done: str | None
    story_points: int | None

    is_blocked: bool
    blocked_reason: str | None

    start_at: datetime | None
    due_at: datetime | None
    completed_at: datetime | None

    position: float
    created_at: datetime
    updated_at: datetime


class ActivityOut(BaseModel):
    id: UUID
    actor_id: UUID | None
    action: str
    data: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MoveTask(BaseModel):
    """Reorder / move a task on the board (spec §56). Placement is expressed
    relative to neighbours so the backend can compute a fractional position
    without reindexing the whole column."""

    status_id: UUID
    after_id: UUID | None = None  # place directly after this task (None = column top)
    before_id: UUID | None = None  # place directly before this task (None = column bottom)
    reason: str | None = None  # used if the move lands in a BLOCKED-category column


class BoardColumn(BaseModel):
    status_id: UUID
    name: str
    category: str
    position: int
    wip_limit: int | None = None
    wip_exceeded: bool = False
    tasks: list[TaskOut]


class BoardOut(BaseModel):
    project_id: UUID
    columns: list[BoardColumn]
