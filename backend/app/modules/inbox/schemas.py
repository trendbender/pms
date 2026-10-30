from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    INBOX_OUTCOMES_WITH_TASK,
    InboxOutcome,
    InboxStatus,
    Priority,
)


class InboxCreate(BaseModel):
    """Положить входящее. Обязателен только заголовок: смысл жёлоба в том, что
    записать можно, не решая ничего заранее."""

    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    body: str | None = None
    url: str | None = Field(default=None, max_length=1000)
    source: str = Field(default="manual", max_length=30)
    external_id: str | None = Field(default=None, max_length=200)
    for_user_id: UUID | None = None


class InboxUpdate(BaseModel):
    """Правка сырья до разбора: уточнить формулировку, приписать проект, адресата."""

    project_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = None
    url: str | None = Field(default=None, max_length=1000)
    for_user_id: UUID | None = None


class InboxResolve(BaseModel):
    """Разбор пункта: один из шести исходов (P-002).

    Исходы, заводящие задачу, требуют своей формулировки в `title`: сырьё в
    заголовок задачи не копируется, потому что ровно в этот момент «проверить и
    отправить отчёт» и должно превратиться в следующее конкретное действие.
    """

    outcome: InboxOutcome
    note: str | None = None

    # Для исходов с задачей. Проект нужен, если пункт лежал без проекта.
    project_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    priority: Priority = Priority.MEDIUM
    assignee_id: UUID | None = None
    reviewer_id: UUID | None = None
    initiative_id: UUID | None = None
    due_at: datetime | None = None
    # CALENDAR: момент, на который взято обязательство.
    start_at: datetime | None = None

    # REFERENCE: куда легла справка.
    reference_url: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _outcome_requires_its_own(self) -> "InboxResolve":
        if self.outcome in INBOX_OUTCOMES_WITH_TASK and not self.title:
            raise ValueError("нужно следующее конкретное действие в title")
        if self.outcome == InboxOutcome.DELEGATED and self.assignee_id is None:
            raise ValueError("делегировать можно только кому-то: нужен assignee_id")
        if self.outcome == InboxOutcome.CALENDAR and self.start_at is None:
            raise ValueError("в календарь — только с датой-обязательством: нужен start_at")
        if self.outcome == InboxOutcome.REFERENCE and not (self.reference_url or self.note):
            raise ValueError("справка должна куда-то лечь: нужен reference_url или note")
        return self


class InboxOut(BaseModel):
    id: UUID
    project_id: UUID | None
    title: str
    body: str | None
    url: str | None
    source: str
    external_id: str | None
    for_user_id: UUID | None
    created_by_id: UUID | None
    status: InboxStatus
    outcome: InboxOutcome | None
    outcome_note: str | None
    task_id: UUID | None
    reference_url: str | None
    resolved_at: datetime | None
    resolved_by_id: UUID | None
    created_at: datetime

    # заполняются роутером, чтобы список читался без второго запроса
    project_code: str | None = None
    task_key: str | None = None

    model_config = {"from_attributes": True}


class InboxProjectCount(BaseModel):
    project_id: UUID | None
    project_code: str | None
    new: int


class InboxCount(BaseModel):
    """Счётчик для навигации и утреннего дайджеста: сколько ждёт разбора."""

    new: int
    by_project: list[InboxProjectCount]
