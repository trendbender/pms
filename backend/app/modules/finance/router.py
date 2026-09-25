from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id, require_project_permission
from app.models.enums import PaymentStatus
from app.models.finance import Contract, Payment
from app.models.initiative import Initiative
from app.models.project import Project
from app.models.user import User
from app.modules.finance import service
from app.modules.finance.schemas import (
    CalendarOut,
    ContractCreate,
    ContractOut,
    ContractUpdate,
    PaymentCreate,
    PaymentInvoice,
    PaymentOut,
    PaymentPaid,
    PaymentUpdate,
)
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm

router = APIRouter(tags=["finance"])


async def _projects_for_finance(
    db: AsyncSession, user: User, workspace_id: UUID
) -> dict[UUID, Project]:
    return await service.finance_project_ids(db, user.id, workspace_id)


async def load_payment(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> Payment:
    obj = await db.get(Payment, payment_id)
    if obj is None or obj.workspace_id != workspace_id or obj.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, obj.project_id, Perm.FINANCE_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    return obj


async def _require_manage(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, project_id: UUID
) -> None:
    if not await perms.has_project_permission(
        db, user_id, workspace_id, project_id, Perm.FINANCE_MANAGE
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: finance.manage")


async def _check_links(
    db: AsyncSession,
    project_id: UUID,
    contract_id: UUID | None,
    initiative_id: UUID | None,
) -> None:
    """Договор и веха должны принадлежать тому же проекту, что и платёж."""
    if contract_id is not None:
        contract = await db.get(Contract, contract_id)
        if contract is None or contract.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Contract belongs to another project")
    if initiative_id is not None:
        initiative = await db.get(Initiative, initiative_id)
        if initiative is None or initiative.project_id != project_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Initiative belongs to another project"
            )


# ---------------------------------------------------------------- payments


@router.get("/finance/payments", response_model=list[PaymentOut])
async def list_payments(
    project_id: UUID | None = None,
    payment_status: PaymentStatus | None = Query(default=None, alias="status"),
    include_paid: bool = True,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentOut]:
    projects = await _projects_for_finance(db, user, workspace_id)
    if project_id and project_id not in projects:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return await service.list_payments(
        db,
        projects,
        project_id=project_id,
        status=payment_status.value if payment_status else None,
        include_paid=include_paid,
    )


@router.get("/finance/calendar", response_model=CalendarOut)
async def payment_calendar(
    weeks: int = Query(default=4, ge=1, le=52),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> CalendarOut:
    projects = await _projects_for_finance(db, user, workspace_id)
    return await service.calendar(db, projects, weeks=weeks)


@router.post(
    "/projects/{project_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    project_id: UUID,
    body: PaymentCreate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.FINANCE_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> PaymentOut:
    await _check_links(db, project_id, body.contract_id, body.initiative_id)
    obj = Payment(
        workspace_id=workspace_id,
        project_id=project_id,
        created_by_id=user.id,
        **body.model_dump(),
    )
    db.add(obj)
    await db.flush()
    project = await db.get(Project, project_id)
    return service.to_out(obj, project)


@router.get("/projects/{project_id}/payments", response_model=list[PaymentOut])
async def project_payments(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.FINANCE_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentOut]:
    project = await db.get(Project, project_id)
    return await service.list_payments(db, {project_id: project}, project_id=project_id)


@router.patch("/finance/payments/{payment_id}", response_model=PaymentOut)
async def update_payment(
    body: PaymentUpdate,
    payment: Payment = Depends(load_payment),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> PaymentOut:
    await _require_manage(db, user.id, workspace_id, payment.project_id)
    patch = body.model_dump(exclude_unset=True)
    if "contract_id" in patch or "initiative_id" in patch:
        await _check_links(
            db,
            payment.project_id,
            patch.get("contract_id", payment.contract_id),
            patch.get("initiative_id", payment.initiative_id),
        )
    for field, value in patch.items():
        setattr(payment, field, value)
    await db.flush()
    return service.to_out(payment, await db.get(Project, payment.project_id))


@router.post("/finance/payments/{payment_id}/invoice", response_model=PaymentOut)
async def mark_invoiced(
    body: PaymentInvoice,
    payment: Payment = Depends(load_payment),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> PaymentOut:
    await _require_manage(db, user.id, workspace_id, payment.project_id)
    payment.status = PaymentStatus.INVOICED.value
    payment.invoiced_at = body.invoiced_at or date.today()
    if body.invoice_no:
        payment.invoice_no = body.invoice_no
    if body.due_date:
        payment.due_date = body.due_date
    await db.flush()
    return service.to_out(payment, await db.get(Project, payment.project_id))


@router.post("/finance/payments/{payment_id}/paid", response_model=PaymentOut)
async def mark_paid(
    body: PaymentPaid,
    payment: Payment = Depends(load_payment),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> PaymentOut:
    await _require_manage(db, user.id, workspace_id, payment.project_id)
    payment.status = PaymentStatus.PAID.value
    payment.paid_at = body.paid_at or date.today()
    if body.amount is not None:
        payment.amount = body.amount
    if body.act_no:
        payment.act_no = body.act_no
    await db.flush()
    return service.to_out(payment, await db.get(Project, payment.project_id))


@router.delete("/finance/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment(
    payment: Payment = Depends(load_payment),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_manage(db, user.id, workspace_id, payment.project_id)
    # Мягкое удаление: платёж это финансовая история, физически её не стираем.
    payment.deleted_at = datetime.now(UTC)
    await db.flush()
    return None


# --------------------------------------------------------------- contracts


@router.get("/projects/{project_id}/contracts", response_model=list[ContractOut])
async def list_contracts(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.FINANCE_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[ContractOut]:
    stmt = (
        select(Contract)
        .where(Contract.project_id == project_id)
        .order_by(Contract.created_at.desc())
    )
    return list((await db.scalars(stmt)).all())


@router.post(
    "/projects/{project_id}/contracts",
    response_model=ContractOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract(
    project_id: UUID,
    body: ContractCreate,
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.FINANCE_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> ContractOut:
    obj = Contract(workspace_id=workspace_id, project_id=project_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    return obj


@router.patch("/finance/contracts/{contract_id}", response_model=ContractOut)
async def update_contract(
    contract_id: UUID,
    body: ContractUpdate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> ContractOut:
    obj = await db.get(Contract, contract_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, obj.project_id, Perm.FINANCE_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    await _require_manage(db, user.id, workspace_id, obj.project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj
