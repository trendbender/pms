from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import RoadmapStatus


class RoadmapCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    period_start: date
    period_end: date | None = None
    status: RoadmapStatus = RoadmapStatus.DRAFT
    goal: str | None = None
    scope_note: str | None = None
    agreed_on: date | None = None
    decision_ref: str | None = Field(default=None, max_length=40)
    plan_url: str | None = Field(default=None, max_length=1000)
    report_url: str | None = Field(default=None, max_length=1000)


class RoadmapUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    period_start: date | None = None
    period_end: date | None = None
    status: RoadmapStatus | None = None
    goal: str | None = None
    scope_note: str | None = None
    agreed_on: date | None = None
    decision_ref: str | None = Field(default=None, max_length=40)
    plan_url: str | None = Field(default=None, max_length=1000)
    report_url: str | None = Field(default=None, max_length=1000)


class MetricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    baseline: str | None = None
    baseline_on: date | None = None
    target: str | None = None
    current: str | None = None
    measured_on: date | None = None
    source: str | None = Field(default=None, max_length=255)
    reached_on: date | None = None
    position: int | None = None


class MetricUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    baseline: str | None = None
    baseline_on: date | None = None
    target: str | None = None
    current: str | None = None
    measured_on: date | None = None
    source: str | None = Field(default=None, max_length=255)
    reached_on: date | None = None
    position: int | None = None


class MetricOut(BaseModel):
    id: UUID
    roadmap_id: UUID
    name: str
    baseline: str | None
    baseline_on: date | None
    target: str | None
    current: str | None
    measured_on: date | None
    source: str | None
    reached_on: date | None
    position: int

    model_config = {"from_attributes": True}


class RoadmapOut(BaseModel):
    id: UUID
    project_id: UUID
    project_code: str | None = None
    project_name: str | None = None
    title: str
    period_start: date
    period_end: date | None
    status: str
    goal: str | None
    scope_note: str | None
    agreed_on: date | None
    decision_ref: str | None
    plan_url: str | None
    report_url: str | None
    archived_at: datetime | None
    created_at: datetime

    wave_count: int = 0
    task_count: int = 0
    done_count: int = 0
    blocked_count: int = 0
    overdue_count: int = 0
    metric_count: int = 0
    metric_reached_count: int = 0


class RoadmapTaskOut(BaseModel):
    """Пункт плана в том виде, в каком он нужен роадмапу и отчёту."""

    id: UUID
    key: str
    title: str
    status_name: str | None
    status_category: str | None
    priority: str
    assignee_name: str | None
    due_at: datetime | None
    completed_at: datetime | None
    is_blocked: bool
    blocked_reason: str | None


class WaveOut(BaseModel):
    """Волна роадмапа — инициатива с его id (неделя, пакет работ, выкладка)."""

    id: UUID
    name: str
    description: str | None
    due_date: date | None
    task_count: int = 0
    done_count: int = 0
    tasks: list[RoadmapTaskOut] = []


class OpenDecisionOut(BaseModel):
    """Открытый вопрос из копии реестра решений: «нужно от владельца и клиента»."""

    ref: str
    registry: str
    area_title: str | None
    question: str


class RoadmapDetail(RoadmapOut):
    waves: list[WaveOut] = []
    metrics: list[MetricOut] = []
    waiting: list[RoadmapTaskOut] = []
    open_decisions: list[OpenDecisionOut] = []
