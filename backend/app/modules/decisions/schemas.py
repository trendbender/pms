from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DecisionItem(BaseModel):
    """Запись реестра в том виде, как её отдаёт `decisions.py export-pms`."""

    ref: str = Field(min_length=3, max_length=20)
    status: str = Field(max_length=20)
    question: str
    area: str | None = Field(default=None, max_length=40)
    area_title: str | None = Field(default=None, max_length=100)
    decision: str | None = None
    decided_by: str | None = Field(default=None, max_length=200)
    decided_on: str | None = Field(default=None, max_length=20)
    source: str | None = None
    applies: str | None = None
    supersedes: str | None = Field(default=None, max_length=20)
    superseded_by: str | None = Field(default=None, max_length=20)
    keys: list[str] = []
    aliases: list[str] = []
    tasks: list[str] = []


class RegistryIn(BaseModel):
    registry: str = Field(min_length=1, max_length=64)
    project_code: str | None = None  # None у `_global`
    items: list[DecisionItem]


class DecisionsSync(BaseModel):
    registries: list[RegistryIn]


class RegistrySynced(BaseModel):
    registry: str
    project_code: str | None
    total: int
    created: int
    updated: int
    deleted: int
    skipped: str | None = None  # почему реестр не принят (нет проекта в PMS)


class DecisionsSyncOut(BaseModel):
    registries: list[RegistrySynced]


class DecisionTask(BaseModel):
    key: str
    title: str
    status_name: str
    status_category: str


class DecisionOut(BaseModel):
    id: UUID
    registry: str
    project_id: UUID | None
    project_code: str | None
    ref: str
    full_ref: str  # для ссылки /d/<full_ref>: SSK-P-030, G-P-022
    area: str | None
    area_title: str | None
    status: str
    question: str
    decision: str | None
    decided_by: str | None
    decided_on: str | None
    source: str | None
    applies: str | None
    supersedes: str | None
    superseded_by: str | None
    keys: list[str]
    aliases: list[str]
    task_keys: list[str]
    synced_at: datetime


class DecisionDetail(DecisionOut):
    tasks: list[DecisionTask] = []
