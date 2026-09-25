"""Агрегация по деньгам.

Все выборки скоуплены проектами, которые пользователь вправе видеть, и ещё раз
режутся правом finance.view: деньги видит управляющий уровень, а не каждый
участник проекта.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PaymentStatus
from app.models.finance import Payment
from app.models.project import Project
from app.modules.finance.schemas import CalendarOut, PaymentOut, ProjectMoney
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.projects.service import list_visible_projects

_OPEN = (PaymentStatus.EXPECTED.value, PaymentStatus.INVOICED.value)


def is_overdue(p: Payment, today: date | None = None) -> bool:
    today = today or date.today()
    return bool(p.due_date and p.due_date < today and p.status in _OPEN)


def to_out(p: Payment, project: Project | None = None, today: date | None = None) -> PaymentOut:
    out = PaymentOut.model_validate(p)
    out.is_overdue = is_overdue(p, today)
    if project is not None:
        out.project_code = project.code
        out.project_name = project.name
    return out


async def finance_project_ids(
    db: AsyncSession, user_id: UUID, workspace_id: UUID
) -> dict[UUID, Project]:
    """Проекты, по которым этот пользователь вправе смотреть деньги."""
    visible = await list_visible_projects(db, user_id, workspace_id)
    allowed: dict[UUID, Project] = {}
    for p in visible:
        if await perms.has_project_permission(
            db, user_id, workspace_id, p.id, Perm.FINANCE_VIEW
        ):
            allowed[p.id] = p
    return allowed


def _base_query(project_ids: list[UUID]) -> Select:
    return (
        select(Payment)
        .where(Payment.deleted_at.is_(None), Payment.project_id.in_(project_ids))
        .order_by(Payment.due_date.is_(None), Payment.due_date, Payment.created_at)
    )


async def list_payments(
    db: AsyncSession,
    projects: dict[UUID, Project],
    *,
    project_id: UUID | None = None,
    status: str | None = None,
    include_paid: bool = True,
) -> list[PaymentOut]:
    ids = [project_id] if project_id else list(projects)
    if not ids:
        return []
    stmt = _base_query(ids)
    if status:
        stmt = stmt.where(Payment.status == status)
    elif not include_paid:
        stmt = stmt.where(Payment.status.in_(_OPEN))
    rows = list((await db.scalars(stmt)).all())
    today = date.today()
    return [to_out(p, projects.get(p.project_id), today) for p in rows]


async def calendar(
    db: AsyncSession, projects: dict[UUID, Project], *, weeks: int = 4
) -> CalendarOut:
    """Календарь платежей: просрочка, ближайшая неделя, горизонт прогноза."""
    today = date.today()
    horizon = today + timedelta(weeks=weeks)
    week_end = today + timedelta(days=7)
    if not projects:
        return CalendarOut(
            today=today,
            overdue=[],
            due_soon=[],
            upcoming=[],
            recently_paid=[],
            unbilled_milestones=[],
            by_project=[],
            forecast_until=horizon,
        )

    rows = list((await db.scalars(_base_query(list(projects)))).all())

    overdue: list[PaymentOut] = []
    due_soon: list[PaymentOut] = []
    upcoming: list[PaymentOut] = []
    recently_paid: list[PaymentOut] = []
    unbilled: list[PaymentOut] = []
    money: dict[UUID, ProjectMoney] = {}
    total_overdue = Decimal(0)
    total_open = Decimal(0)
    forecast = Decimal(0)

    for p in rows:
        project = projects.get(p.project_id)
        card = to_out(p, project, today)
        pm = money.get(p.project_id)
        if pm is None and project is not None:
            pm = ProjectMoney(
                project_id=project.id, code=project.code, name=project.name, currency=p.currency
            )
            money[p.project_id] = pm

        if p.status == PaymentStatus.PAID.value:
            if pm:
                pm.paid_total += p.amount
            if p.paid_at and p.paid_at >= today - timedelta(days=7):
                recently_paid.append(card)
            continue
        if p.status == PaymentStatus.CANCELLED.value:
            continue

        total_open += p.amount
        if pm:
            if p.status == PaymentStatus.INVOICED.value:
                pm.invoiced += p.amount
            else:
                pm.expected += p.amount

        if card.is_overdue:
            overdue.append(card)
            total_overdue += p.amount
            if pm:
                pm.overdue += p.amount
        elif p.due_date and p.due_date <= week_end:
            due_soon.append(card)
        elif p.due_date and p.due_date <= horizon:
            upcoming.append(card)

        if p.due_date and p.due_date <= horizon:
            forecast += p.amount

        # Веха с датой в прошлом, а счёт не выставлен: деньги, о которых забыли.
        if (
            p.initiative_id
            and p.status == PaymentStatus.EXPECTED.value
            and p.due_date
            and p.due_date <= today
        ):
            unbilled.append(card)

        if pm and p.due_date and (pm.next_due_date is None or p.due_date < pm.next_due_date):
            pm.next_due_date = p.due_date
            pm.next_due_amount = p.amount

    by_project = sorted(
        (m for m in money.values() if m.expected or m.invoiced or m.overdue or m.paid_total),
        key=lambda m: (-m.overdue, -(m.expected + m.invoiced), m.code),
    )
    return CalendarOut(
        today=today,
        overdue=overdue,
        due_soon=due_soon,
        upcoming=upcoming,
        recently_paid=recently_paid,
        unbilled_milestones=unbilled,
        by_project=by_project,
        total_overdue=total_overdue,
        total_open=total_open,
        forecast_amount=forecast,
        forecast_until=horizon,
    )
