"""Деньги проекта: договор и платежи.

Отдельная строка на каждый платёж, а не одна сумма на договор: именно строки
складываются в календарь платежей и в прогноз поступлений. Просрочка нигде не
хранится, она выводится из `due_date` и статуса, иначе пришлось бы гонять
ночной джоб, который переписывает статусы и врёт при первом же сбое.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Contract(Base, TimestampMixin):
    """Договорённость с клиентом: рамка, из которой растут платежи."""

    __tablename__ = "contracts"

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="FIXED")

    # Сумма договора для FIXED/MILESTONE, ставка за час или месяц для HOURLY/RETAINER.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")

    signed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Документ лежит в Drive, а не в git: сюда пишем только ссылку.
    doc_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Payment(Base, TimestampMixin):
    """Один ожидаемый или полученный платёж."""

    __tablename__ = "payments"

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Связь с вехой: закрытая веха без выставленного счёта это отдельная строка в отчёте.
    initiative_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("initiatives.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="MILESTONE")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="EXPECTED", index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    invoiced_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    invoice_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    act_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    doc_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
