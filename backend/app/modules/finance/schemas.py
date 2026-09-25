from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ContractType, PaymentKind, PaymentStatus


class ContractCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    kind: ContractType = ContractType.FIXED
    amount: Decimal | None = Field(default=None, ge=0)
    rate: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    signed_at: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    doc_url: str | None = Field(default=None, max_length=1000)
    note: str | None = None


class ContractUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    kind: ContractType | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    rate: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    signed_at: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    doc_url: str | None = Field(default=None, max_length=1000)
    note: str | None = None
    is_active: bool | None = None


class ContractOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    kind: str
    amount: Decimal | None
    rate: Decimal | None
    currency: str
    signed_at: date | None
    start_date: date | None
    end_date: date | None
    doc_url: str | None
    note: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=0)
    kind: PaymentKind = PaymentKind.MILESTONE
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    due_date: date | None = None
    contract_id: UUID | None = None
    initiative_id: UUID | None = None
    invoice_no: str | None = Field(default=None, max_length=50)
    act_no: str | None = Field(default=None, max_length=50)
    doc_url: str | None = Field(default=None, max_length=1000)
    note: str | None = None


class PaymentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, gt=0)
    kind: PaymentKind | None = None
    status: PaymentStatus | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    due_date: date | None = None
    invoiced_at: date | None = None
    paid_at: date | None = None
    contract_id: UUID | None = None
    initiative_id: UUID | None = None
    invoice_no: str | None = Field(default=None, max_length=50)
    act_no: str | None = Field(default=None, max_length=50)
    doc_url: str | None = Field(default=None, max_length=1000)
    note: str | None = None


class PaymentInvoice(BaseModel):
    invoice_no: str | None = Field(default=None, max_length=50)
    invoiced_at: date | None = None
    due_date: date | None = None


class PaymentPaid(BaseModel):
    paid_at: date | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    act_no: str | None = Field(default=None, max_length=50)


class PaymentOut(BaseModel):
    id: UUID
    project_id: UUID
    project_code: str | None = None
    project_name: str | None = None
    contract_id: UUID | None
    initiative_id: UUID | None
    title: str
    kind: str
    status: str
    amount: Decimal
    currency: str
    due_date: date | None
    invoiced_at: date | None
    paid_at: date | None
    invoice_no: str | None
    act_no: str | None
    doc_url: str | None
    note: str | None
    # Считается на лету: платёж просрочен, если срок в прошлом, а денег нет.
    is_overdue: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectMoney(BaseModel):
    """Свод по одному проекту: сколько ждём, сколько висит, сколько получено."""

    project_id: UUID
    code: str
    name: str
    currency: str = "RUB"
    expected: Decimal = Decimal(0)
    invoiced: Decimal = Decimal(0)
    overdue: Decimal = Decimal(0)
    paid_total: Decimal = Decimal(0)
    next_due_date: date | None = None
    next_due_amount: Decimal | None = None


class CalendarOut(BaseModel):
    today: date
    overdue: list[PaymentOut]
    due_soon: list[PaymentOut]
    upcoming: list[PaymentOut]
    recently_paid: list[PaymentOut]
    # Вехи, которые закрыты или просрочены, а счёт по ним так и не выставлен.
    unbilled_milestones: list[PaymentOut]
    by_project: list[ProjectMoney]
    total_overdue: Decimal = Decimal(0)
    total_open: Decimal = Decimal(0)
    forecast_amount: Decimal = Decimal(0)
    forecast_until: date | None = None
