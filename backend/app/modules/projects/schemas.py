import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.links import normalize_site_url
from app.models.enums import (
    ProjectHealth,
    ProjectRole,
    ProjectStatus,
    StatusCategory,
)

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,19}$")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=20)
    description: str | None = None
    goal: str | None = None
    group_name: str | None = Field(default=None, max_length=60)
    site_url: str | None = Field(default=None, max_length=255)
    wip_limit: int | None = Field(default=None, ge=1, le=100)

    @field_validator("site_url")
    @classmethod
    def _normalize_site_url(cls, v: str | None) -> str | None:
        return normalize_site_url(v)

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not _CODE_RE.match(v):
            raise ValueError("code must be 1–20 chars, start with a letter, A–Z/0–9 only")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    goal: str | None = None
    group_name: str | None = Field(default=None, max_length=60)
    # "" очищает поле
    site_url: str | None = Field(default=None, max_length=255)
    status: ProjectStatus | None = None
    health: ProjectHealth | None = None
    wip_limit: int | None = Field(default=None, ge=1, le=100)
    owner_id: UUID | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None

    @field_validator("site_url")
    @classmethod
    def _normalize_site_url(cls, v: str | None) -> str | None:
        return normalize_site_url(v)


class ProjectOut(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    code: str
    description: str | None
    goal: str | None
    status: str
    health: str
    group_name: str | None
    site_url: str | None = None
    owner_id: UUID | None
    wip_limit: int | None
    start_date: datetime | None
    due_date: datetime | None
    archived_at: datetime | None
    created_at: datetime
    leads_enabled: bool = False

    model_config = {"from_attributes": True}


# ---- members ----


class MemberUpsert(BaseModel):
    user_id: UUID
    role: ProjectRole = ProjectRole.MEMBER


class MemberOut(BaseModel):
    user_id: UUID
    email: EmailStr
    name: str
    role: str


# ---- workflow config: statuses & types ----


class StatusCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    category: StatusCategory
    position: int | None = Field(default=None, ge=0)


class StatusUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    category: StatusCategory | None = None
    position: int | None = Field(default=None, ge=0)


class StatusOut(BaseModel):
    id: UUID
    name: str
    category: str
    position: int

    model_config = {"from_attributes": True}


class TypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    position: int | None = Field(default=None, ge=0)


class TypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    position: int | None = Field(default=None, ge=0)


class TypeOut(BaseModel):
    id: UUID
    name: str
    position: int

    model_config = {"from_attributes": True}
