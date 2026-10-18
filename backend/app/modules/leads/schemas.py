from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import LeadFieldType, LeadStageCategory

_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


# ---------------------------------------------------------------- settings


class LeadsEnable(BaseModel):
    preset: Literal["sales", "orders", "basic"] = "basic"


class StageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: LeadStageCategory = LeadStageCategory.OPEN
    position: int | None = None
    color: str | None = Field(default=None, max_length=20)


class StageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: LeadStageCategory | None = None
    position: int | None = None
    color: str | None = Field(default=None, max_length=20)


class StageOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    category: str
    position: int
    color: str | None

    model_config = {"from_attributes": True}


class FieldCreate(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=100)
    type: LeadFieldType = LeadFieldType.TEXT
    options: list[str] | None = None
    required: bool = False
    is_pii: bool = False
    position: int | None = None

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip().lower()
        if not set(v) <= _KEY_CHARS or v[0].isdigit():
            raise ValueError("key: a-z, 0-9 and _, must not start with a digit")
        return v


class FieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    options: list[str] | None = None
    required: bool | None = None
    is_pii: bool | None = None
    position: int | None = None


class FieldOut(BaseModel):
    id: UUID
    project_id: UUID
    key: str
    label: str
    type: str
    options: list[str] | None
    required: bool
    is_pii: bool
    position: int

    model_config = {"from_attributes": True}


class TokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)


class TokenOut(BaseModel):
    id: UUID
    label: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class TokenCreated(TokenOut):
    # значение ключа отдаётся только в ответе на создание
    token: str


class LeadSettingsOut(BaseModel):
    enabled: bool
    stages: list[StageOut]
    fields: list[FieldOut]
    tokens: list[TokenOut] | None = None  # только с правом lead.settings


# ------------------------------------------------------------------- leads


class _LeadBase(BaseModel):
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source_url: str | None = Field(default=None, max_length=1000)
    data: dict[str, Any] | None = None


class LeadCreate(_LeadBase):
    title: str = Field(min_length=1, max_length=500)
    stage_id: UUID | None = None
    owner_id: UUID | None = None
    source: str = Field(default="manual", min_length=1, max_length=30)
    external_id: str | None = Field(default=None, max_length=200)
    received_at: datetime | None = None


class LeadUpdate(_LeadBase):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    owner_id: UUID | None = None
    source: str | None = Field(default=None, min_length=1, max_length=30)
    duplicate_of_id: UUID | None = None


class LeadStageChange(BaseModel):
    stage_id: UUID | None = None
    stage: str | None = None  # по имени этапа, удобно для CLI и скриптов
    lost_reason: str | None = None


class LeadOut(BaseModel):
    id: UUID
    project_id: UUID
    key: str
    number: int
    title: str
    stage_id: UUID
    stage_name: str
    stage_category: str
    owner_id: UUID | None
    source: str
    source_url: str | None
    external_id: str | None
    contact_name: str | None
    phone: str | None
    email: str | None
    amount: Decimal | None
    currency: str
    data: dict[str, Any]
    received_at: datetime
    closed_at: datetime | None
    lost_reason: str | None
    task_id: UUID | None
    task_key: str | None = None
    duplicate_of_id: UUID | None
    created_at: datetime
    updated_at: datetime


class LeadEventOut(BaseModel):
    id: UUID
    action: str
    actor_id: UUID | None
    token_id: UUID | None
    data: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadComment(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


class LeadTaskCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    assignee_id: UUID | None = None
    priority: str = "MEDIUM"


class BoardColumn(BaseModel):
    stage: StageOut
    leads: list[LeadOut]
    count: int
    amount: Decimal


class LeadBoardOut(BaseModel):
    columns: list[BoardColumn]


class StageStat(BaseModel):
    stage_id: UUID
    name: str
    category: str
    count: int        # сейчас на этапе
    reached: int      # побывали на этапе за период (воронка)
    amount: Decimal


class SourceStat(BaseModel):
    source: str
    count: int
    won: int
    won_amount: Decimal


class LeadStatsOut(BaseModel):
    period_from: datetime
    period_to: datetime
    total: int
    open: int
    won: int
    lost: int
    win_rate: float | None       # won / (won + lost)
    open_amount: Decimal
    won_amount: Decimal
    avg_days_to_close: float | None
    stages: list[StageStat]
    sources: list[SourceStat]


# ----------------------------------------------------------------- ingest


class LeadIngest(_LeadBase):
    """Тело приёма по ключу проекта. Повтор с тем же (source, external_id)
    не создаёт дубль: пишется событие, а при `update=true` применяются поля."""

    title: str | None = Field(default=None, max_length=500)
    source: str = Field(default="api", min_length=1, max_length=30)
    external_id: str | None = Field(default=None, max_length=200)
    stage: str | None = None
    lost_reason: str | None = None
    received_at: datetime | None = None
    update: bool = False


class LeadIngestOut(BaseModel):
    id: UUID
    key: str
    url: str
    created: bool
    stage_name: str
