from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import SUPPORTED_LANGUAGES, SystemRole


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    is_active: bool
    is_suspended: bool
    language: str = "ru"
    system_role: str | None = None

    model_config = {"from_attributes": True}


class UpdateMeRequest(BaseModel):
    """Self-service profile update (name + UI language)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    language: str | None = None

    @field_validator("language")
    @classmethod
    def _known_language(cls, v: str | None) -> str | None:
        if v is not None and v not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language; expected one of {sorted(SUPPORTED_LANGUAGES)}")
        return v


class InviteUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    system_role: SystemRole = SystemRole.MEMBER
    # MVP convenience: set an initial password so the account is usable before
    # the email-invitation flow exists (Sprint 7). Optional.
    initial_password: str | None = Field(default=None, min_length=8, max_length=200)


class UpdateUserRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    system_role: SystemRole | None = None
    is_suspended: bool | None = None
