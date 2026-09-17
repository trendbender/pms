from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TaskCard(BaseModel):
    """Compact cross-project task row for management screens (My Tasks, reviews, All)."""

    id: UUID
    key: str
    title: str
    priority: str
    status_name: str | None
    status_category: str | None
    due_at: datetime | None
    is_blocked: bool
    assignee_id: UUID | None
    reviewer_id: UUID | None
    sprint_id: UUID | None
    project_id: UUID
    project_code: str
    project_name: str


class PagedTasks(BaseModel):
    items: list[TaskCard]
    total: int
    limit: int
    offset: int


class PortfolioRow(BaseModel):
    project_id: UUID
    code: str
    name: str
    health: str
    status: str
    group_name: str | None = None
    open: int = 0
    overdue: int = 0
    blocked: int = 0
    review: int = 0
    sprint_name: str | None = None
    sprint_done: int = 0
    sprint_total: int = 0


class PortfolioTotals(BaseModel):
    active_projects: int = 0
    blockers: int = 0
    overdue: int = 0
    waiting_my_review: int = 0


class PortfolioOut(BaseModel):
    rows: list[PortfolioRow]
    totals: PortfolioTotals


class SprintBrief(BaseModel):
    id: UUID
    name: str
    goal: str | None
    done: int
    total: int


class ProjectDashboard(BaseModel):
    project_id: UUID
    code: str
    name: str
    goal: str | None
    health: str
    status: str
    open: int = 0
    overdue: int = 0
    blocked: int = 0
    waiting_review: int = 0
    current_sprint: SprintBrief | None = None
