from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    DEFAULT_REMINDER_TZ,
    ChannelKind,
    OutboxStatus,
    ReminderSchedule,
    ReminderStatus,
)


class ReminderCreate(BaseModel):
    schedule: ReminderSchedule = ReminderSchedule.ONCE
    at_time: time = time(10, 0)
    timezone: str = Field(default=DEFAULT_REMINDER_TZ, max_length=64)
    weekday: int | None = Field(default=None, ge=0, le=6)

    start_on: date | None = None
    # «за два дня до срока» = -2. Расписание тогда считается от срока задачи.
    due_offset_days: int | None = None

    until_on: date | None = None
    max_fires: int | None = Field(default=None, ge=1)
    stop_on_done: bool = True

    escalate_after_fires: int | None = Field(default=None, ge=1)
    escalate_to_id: UUID | None = None

    channel_id: UUID | None = None
    notify_user_id: UUID | None = None
    mention: str | None = Field(default=None, max_length=100)
    message: str | None = None
    comment_on_task: bool = False

    @model_validator(mode="after")
    def _needs_a_starting_point(self) -> "ReminderCreate":
        if self.start_on is None and self.due_offset_days is None:
            raise ValueError("нужен start_on или due_offset_days")
        return self


class ReminderUpdate(BaseModel):
    schedule: ReminderSchedule | None = None
    at_time: time | None = None
    timezone: str | None = Field(default=None, max_length=64)
    weekday: int | None = Field(default=None, ge=0, le=6)
    start_on: date | None = None
    due_offset_days: int | None = None
    until_on: date | None = None
    max_fires: int | None = Field(default=None, ge=1)
    stop_on_done: bool | None = None
    escalate_after_fires: int | None = Field(default=None, ge=1)
    escalate_to_id: UUID | None = None
    channel_id: UUID | None = None
    notify_user_id: UUID | None = None
    mention: str | None = Field(default=None, max_length=100)
    message: str | None = None
    comment_on_task: bool | None = None


class SnoozeRequest(BaseModel):
    """Перенос напоминания: до момента или на N дней вперёд."""

    until: datetime | None = None
    days: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_of(self) -> "SnoozeRequest":
        if (self.until is None) == (self.days is None):
            raise ValueError("нужно одно из двух: until или days")
        return self


class OutboxOut(BaseModel):
    id: UUID
    kind: str
    address: str
    body: str
    scheduled_for: datetime
    status: OutboxStatus
    attempts: int
    sent_at: datetime | None
    error: str | None

    model_config = {"from_attributes": True}


class ReminderOut(BaseModel):
    id: UUID
    project_id: UUID
    task_id: UUID
    task_key: str | None = None

    schedule: ReminderSchedule
    at_time: time
    timezone: str
    weekday: int | None
    start_on: date
    due_offset_days: int | None
    until_on: date | None
    max_fires: int | None
    stop_on_done: bool

    escalate_after_fires: int | None
    escalate_to_id: UUID | None
    channel_id: UUID | None
    notify_user_id: UUID | None
    mention: str | None
    message: str | None
    comment_on_task: bool

    status: ReminderStatus
    next_fire_at: datetime | None
    last_fire_at: datetime | None
    fire_count: int
    stop_reason: str | None
    created_by_id: UUID | None

    model_config = {"from_attributes": True}


class ReminderDetail(ReminderOut):
    log: list[OutboxOut] = []


class ChannelCreate(BaseModel):
    kind: ChannelKind = ChannelKind.TELEGRAM
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=200)
    thread_id: str | None = Field(default=None, max_length=50)
    is_default: bool = False
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    address: str | None = Field(default=None, min_length=1, max_length=200)
    thread_id: str | None = Field(default=None, max_length=50)
    is_default: bool | None = None
    enabled: bool | None = None


class ChannelOut(BaseModel):
    id: UUID
    project_id: UUID
    kind: ChannelKind
    name: str
    address: str
    thread_id: str | None
    is_default: bool
    enabled: bool

    model_config = {"from_attributes": True}


class OutboxClaimed(OutboxOut):
    """Строка очереди в том виде, в каком её забирает релей."""

    project_id: UUID | None
    thread_id: str | None
