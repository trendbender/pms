from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import DbSession
from app.core.deps import get_current_user, get_workspace_id, require_project_permission
from app.models.enums import LeadStageCategory, Priority
from app.models.lead import Lead, LeadEvent, LeadField, LeadIngestToken, LeadStage
from app.models.project import Project
from app.models.user import User
from app.modules.leads import service
from app.modules.leads.schemas import (
    BoardColumn,
    FieldCreate,
    FieldOut,
    FieldUpdate,
    LeadBoardOut,
    LeadComment,
    LeadCreate,
    LeadEventOut,
    LeadIngest,
    LeadIngestOut,
    LeadOut,
    LeadsEnable,
    LeadSettingsOut,
    LeadStageChange,
    LeadStatsOut,
    LeadTaskCreate,
    LeadUpdate,
    StageCreate,
    StageOut,
    StageUpdate,
    TokenCreate,
    TokenCreated,
    TokenOut,
)
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from app.modules.tasks import service as task_service

router = APIRouter(tags=["leads"])

_LEAD_SCALARS = ("contact_name", "phone", "email", "amount", "currency", "source_url")


# ------------------------------------------------------------ helpers


async def _project(db: AsyncSession, project_id: UUID, *, enabled: bool = True) -> Project:
    project = await db.get(Project, project_id)
    assert project is not None  # проверено зависимостью прав
    if enabled:
        service.require_enabled(project)
    return project


async def _require(
    db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID, perm: Perm
) -> None:
    if not await perms.has_project_permission(db, user.id, workspace_id, project_id, perm):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")


async def load_lead(
    lead_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> Lead:
    lead = await db.get(Lead, lead_id)
    if lead is None or lead.workspace_id != workspace_id or lead.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, lead.project_id, Perm.LEAD_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    project = await db.get(Project, lead.project_id)
    service.require_enabled(project)
    return lead


async def _check_owner(
    db: AsyncSession, workspace_id: UUID, project_id: UUID, owner_id: UUID | None
) -> None:
    if owner_id is not None and not await perms.has_project_permission(
        db, owner_id, workspace_id, project_id, Perm.LEAD_VIEW
    ):
        raise HTTPException(422, "owner must see project leads")


async def _settings_out(
    db: AsyncSession, project: Project, *, with_tokens: bool
) -> LeadSettingsOut:
    tokens = None
    if with_tokens:
        rows = await db.scalars(
            select(LeadIngestToken)
            .where(LeadIngestToken.project_id == project.id)
            .order_by(LeadIngestToken.created_at)
        )
        tokens = [TokenOut.model_validate(t) for t in rows]
    return LeadSettingsOut(
        enabled=project.leads_enabled,
        stages=[StageOut.model_validate(s) for s in await service.stages(db, project.id)],
        fields=[FieldOut.model_validate(f) for f in await service.fields(db, project.id)],
        tokens=tokens,
    )


def _lead_url(lead: Lead) -> str:
    return f"{settings.public_url.rstrip('/')}/l/{lead.key.lower()}"


# ------------------------------------------------------------ settings


@router.post("/projects/{project_id}/leads/enable", response_model=LeadSettingsOut)
async def enable_leads(
    project_id: UUID,
    body: LeadsEnable,
    _: None = Depends(require_project_permission(Perm.LEAD_SETTINGS)),
    db: AsyncSession = DbSession,
) -> LeadSettingsOut:
    project = await _project(db, project_id, enabled=False)
    await service.seed_preset(db, project, body.preset)
    project.leads_enabled = True
    await db.flush()
    return await _settings_out(db, project, with_tokens=True)


@router.post("/projects/{project_id}/leads/disable", response_model=LeadSettingsOut)
async def disable_leads(
    project_id: UUID,
    _: None = Depends(require_project_permission(Perm.LEAD_SETTINGS)),
    db: AsyncSession = DbSession,
) -> LeadSettingsOut:
    # данные не удаляем: выключение прячет вкладку и закрывает приём
    project = await _project(db, project_id, enabled=False)
    project.leads_enabled = False
    await db.flush()
    return await _settings_out(db, project, with_tokens=True)


@router.get("/projects/{project_id}/leads/settings", response_model=LeadSettingsOut)
async def lead_settings(
    project_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.PROJECT_VIEW)),
    db: AsyncSession = DbSession,
) -> LeadSettingsOut:
    project = await _project(db, project_id, enabled=False)
    can_settings = await perms.has_project_permission(
        db, user.id, workspace_id, project_id, Perm.LEAD_SETTINGS
    )
    if not project.leads_enabled and not can_settings:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leads are not enabled for this project")
    if project.leads_enabled:
        await _require(db, user, workspace_id, project_id, Perm.LEAD_VIEW)
    return await _settings_out(db, project, with_tokens=can_settings)


@router.post(
    "/projects/{project_id}/lead-stages", response_model=StageOut, status_code=201
)
async def create_stage(
    project_id: UUID,
    body: StageCreate,
    _: None = Depends(require_project_permission(Perm.LEAD_SETTINGS)),
    db: AsyncSession = DbSession,
) -> LeadStage:
    project = await _project(db, project_id, enabled=False)
    existing = await service.stages(db, project_id)
    position = body.position if body.position is not None else (
        (existing[-1].position + 10) if existing else 10
    )
    obj = LeadStage(
        workspace_id=project.workspace_id,
        project_id=project_id,
        name=body.name.strip(),
        category=body.category.value,
        position=position,
        color=body.color,
    )
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stage with this name exists") from None
    return obj


async def _load_settings_obj(
    db: AsyncSession, model, obj_id: UUID, user: User, workspace_id: UUID
):
    obj = await db.get(model, obj_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not await perms.has_project_permission(
        db, user.id, workspace_id, obj.project_id, Perm.PROJECT_VIEW
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await _require(db, user, workspace_id, obj.project_id, Perm.LEAD_SETTINGS)
    return obj


@router.patch("/lead-stages/{stage_id}", response_model=StageOut)
async def update_stage(
    stage_id: UUID,
    body: StageUpdate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> LeadStage:
    obj = await _load_settings_obj(db, LeadStage, stage_id, user, workspace_id)
    patch = body.model_dump(exclude_unset=True)
    if "category" in patch and patch["category"] != obj.category:
        # смена смысла этапа под живыми лидами исказит closed_at и статистику
        has_leads = await db.scalar(
            select(func.count(Lead.id)).where(Lead.stage_id == obj.id, Lead.deleted_at.is_(None))
        )
        if has_leads:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Move leads off this stage before changing its category"
            )
    for field, value in patch.items():
        setattr(obj, field, value.value if hasattr(value, "value") else value)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stage with this name exists") from None
    return obj


@router.delete("/lead-stages/{stage_id}", status_code=204)
async def delete_stage(
    stage_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> None:
    obj = await _load_settings_obj(db, LeadStage, stage_id, user, workspace_id)
    used = await db.scalar(select(func.count(Lead.id)).where(Lead.stage_id == obj.id))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stage has leads, move them first")
    await db.delete(obj)
    await db.flush()


@router.post(
    "/projects/{project_id}/lead-fields", response_model=FieldOut, status_code=201
)
async def create_field(
    project_id: UUID,
    body: FieldCreate,
    _: None = Depends(require_project_permission(Perm.LEAD_SETTINGS)),
    db: AsyncSession = DbSession,
) -> LeadField:
    project = await _project(db, project_id, enabled=False)
    if body.type == "select" and not body.options:
        raise HTTPException(422, "select needs options")
    existing = await service.fields(db, project_id)
    position = body.position if body.position is not None else (
        (existing[-1].position + 10) if existing else 10
    )
    obj = LeadField(
        workspace_id=project.workspace_id,
        project_id=project_id,
        key=body.key,
        label=body.label,
        type=body.type.value,
        options=body.options,
        required=body.required,
        is_pii=body.is_pii,
        position=position,
    )
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Field with this key exists") from None
    return obj


@router.patch("/lead-fields/{field_id}", response_model=FieldOut)
async def update_field(
    field_id: UUID,
    body: FieldUpdate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> LeadField:
    obj = await _load_settings_obj(db, LeadField, field_id, user, workspace_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


@router.delete("/lead-fields/{field_id}", status_code=204)
async def delete_field(
    field_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> None:
    # значения в leads.data не трогаем: поле можно вернуть, история не теряется
    obj = await _load_settings_obj(db, LeadField, field_id, user, workspace_id)
    await db.delete(obj)
    await db.flush()


@router.post(
    "/projects/{project_id}/lead-tokens", response_model=TokenCreated, status_code=201
)
async def create_token(
    project_id: UUID,
    body: TokenCreate,
    user: User = Depends(get_current_user),
    _: None = Depends(require_project_permission(Perm.LEAD_SETTINGS)),
    db: AsyncSession = DbSession,
) -> TokenCreated:
    project = await _project(db, project_id, enabled=False)
    raw, token_hash, prefix = service.new_token()
    obj = LeadIngestToken(
        workspace_id=project.workspace_id,
        project_id=project_id,
        label=body.label,
        token_hash=token_hash,
        prefix=prefix,
        created_by_id=user.id,
    )
    db.add(obj)
    await db.flush()
    return TokenCreated(**TokenOut.model_validate(obj).model_dump(), token=raw)


@router.post("/lead-tokens/{token_id}/revoke", response_model=TokenOut)
async def revoke_token(
    token_id: UUID,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> LeadIngestToken:
    obj = await _load_settings_obj(db, LeadIngestToken, token_id, user, workspace_id)
    if obj.revoked_at is None:
        obj.revoked_at = datetime.now(UTC)
        await db.flush()
    return obj


# --------------------------------------------------------------- leads


@router.get("/projects/{project_id}/leads", response_model=list[LeadOut])
async def list_leads(
    project_id: UUID,
    stage_id: UUID | None = None,
    category: LeadStageCategory | None = None,
    source: str | None = None,
    owner_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(require_project_permission(Perm.LEAD_VIEW)),
    db: AsyncSession = DbSession,
) -> list[LeadOut]:
    await _project(db, project_id)
    stmt = select(Lead).where(Lead.project_id == project_id, Lead.deleted_at.is_(None))
    if stage_id:
        stmt = stmt.where(Lead.stage_id == stage_id)
    if category:
        stmt = stmt.join(LeadStage, LeadStage.id == Lead.stage_id).where(
            LeadStage.category == category.value
        )
    if source:
        stmt = stmt.where(Lead.source == source)
    if owner_id:
        stmt = stmt.where(Lead.owner_id == owner_id)
    if received_from:
        stmt = stmt.where(Lead.received_at >= received_from)
    if received_to:
        stmt = stmt.where(Lead.received_at < received_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.title.ilike(like),
                Lead.key.ilike(like),
                Lead.contact_name.ilike(like),
                Lead.phone.ilike(like),
                Lead.email.ilike(like),
                Lead.external_id.ilike(like),
            )
        )
    stmt = stmt.order_by(Lead.received_at.desc()).limit(limit).offset(offset)
    leads = list((await db.scalars(stmt)).all())
    return await service.list_out(db, leads, project_id)


@router.post("/projects/{project_id}/leads", response_model=LeadOut, status_code=201)
async def create_lead(
    project_id: UUID,
    body: LeadCreate,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    _: None = Depends(require_project_permission(Perm.LEAD_MANAGE)),
    db: AsyncSession = DbSession,
) -> LeadOut:
    project = await _project(db, project_id)
    await _check_owner(db, workspace_id, project_id, body.owner_id)
    stage = (
        await service.stage_by_ref(db, project_id, body.stage_id, None)
        if body.stage_id
        else await service.first_open_stage(db, project_id)
    )
    if stage.category == LeadStageCategory.LOST:
        raise HTTPException(422, "Cannot create a lead as LOST")
    data = service.clean_data(await service.fields(db, project_id), body.data, strict=True)
    values = body.model_dump(
        include={*_LEAD_SCALARS, "owner_id", "source", "external_id", "received_at"}
    )
    try:
        async with db.begin_nested():
            lead = await service.create_lead(
                db, project=project, stage=stage, title=body.title,
                values=values, data=data, actor_id=user.id,
            )
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Lead with this source and external_id exists"
        ) from None
    return await service.to_out(db, lead, stage)


@router.get("/projects/{project_id}/leads/board", response_model=LeadBoardOut)
async def lead_board(
    project_id: UUID,
    closed_days: int = Query(default=30, ge=0, le=3650),
    _: None = Depends(require_project_permission(Perm.LEAD_VIEW)),
    db: AsyncSession = DbSession,
) -> LeadBoardOut:
    """Доска по этапам. Закрытые (WON/LOST) показываются только за последние
    `closed_days` дней, иначе колонки «Выигран/Проигран» растут бесконечно."""
    await _project(db, project_id)
    stage_list = await service.stages(db, project_id)
    since = datetime.now(UTC) - timedelta(days=closed_days)
    leads = list(
        (
            await db.scalars(
                select(Lead)
                .where(
                    Lead.project_id == project_id,
                    Lead.deleted_at.is_(None),
                    or_(Lead.closed_at.is_(None), Lead.closed_at >= since),
                )
                .order_by(Lead.received_at.desc())
            )
        ).all()
    )
    outs = await service.list_out(db, leads, project_id)
    columns = []
    for s in stage_list:
        col = [o for o in outs if o.stage_id == s.id]
        columns.append(
            BoardColumn(
                stage=StageOut.model_validate(s),
                leads=col,
                count=len(col),
                amount=sum((o.amount or Decimal("0") for o in col), Decimal("0")),
            )
        )
    return LeadBoardOut(columns=columns)


@router.get("/projects/{project_id}/leads/stats", response_model=LeadStatsOut)
async def lead_stats(
    project_id: UUID,
    period_from: datetime | None = Query(default=None, alias="from"),
    period_to: datetime | None = Query(default=None, alias="to"),
    _: None = Depends(require_project_permission(Perm.LEAD_VIEW)),
    db: AsyncSession = DbSession,
) -> LeadStatsOut:
    await _project(db, project_id)
    now = datetime.now(UTC)
    period_to = period_to or now
    period_from = period_from or (period_to - timedelta(days=30))
    return LeadStatsOut(**await service.stats(db, project_id, period_from, period_to))


@router.get("/leads/by-key/{key}", response_model=LeadOut)
async def get_lead_by_key(
    key: str,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> LeadOut:
    lead = await db.scalar(
        select(Lead).where(
            Lead.workspace_id == workspace_id,
            func.upper(Lead.key) == key.strip().upper(),
            Lead.deleted_at.is_(None),
        )
    )
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    lead = await load_lead(lead.id, user, workspace_id, db)
    return await service.to_out(db, lead)


@router.get("/leads/{lead_id}", response_model=LeadOut)
async def get_lead(lead: Lead = Depends(load_lead), db: AsyncSession = DbSession) -> LeadOut:
    return await service.to_out(db, lead)


@router.patch("/leads/{lead_id}", response_model=LeadOut)
async def update_lead(
    body: LeadUpdate,
    lead: Lead = Depends(load_lead),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> LeadOut:
    await _require(db, user, workspace_id, lead.project_id, Perm.LEAD_MANAGE)
    patch = body.model_dump(exclude_unset=True)
    if "owner_id" in patch:
        await _check_owner(db, workspace_id, lead.project_id, patch["owner_id"])
    if patch.get("duplicate_of_id"):
        dup = await db.get(Lead, patch["duplicate_of_id"])
        if dup is None or dup.project_id != lead.project_id or dup.id == lead.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "duplicate_of must be another lead")
    changed: dict = {}
    if "data" in patch:
        new_data = service.clean_data(
            await service.fields(db, lead.project_id), patch.pop("data"), strict=True,
            current=lead.data,
        )
        if new_data != lead.data:
            changed["data"] = sorted(
                k for k in set(new_data) | set(lead.data or {})
                if (new_data or {}).get(k) != (lead.data or {}).get(k)
            )
            lead.data = new_data
    for field, value in patch.items():
        if getattr(lead, field) != value:
            changed[field] = True
            setattr(lead, field, value)
    if changed:
        await service.record_event(
            db, lead, "lead.updated", actor_id=user.id, data={"fields": sorted(changed)}
        )
    await db.flush()
    await db.refresh(lead)
    return await service.to_out(db, lead)


@router.patch("/leads/{lead_id}/stage", response_model=LeadOut)
async def change_lead_stage(
    body: LeadStageChange,
    lead: Lead = Depends(load_lead),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> LeadOut:
    await _require(db, user, workspace_id, lead.project_id, Perm.LEAD_MANAGE)
    stage = await service.stage_by_ref(db, lead.project_id, body.stage_id, body.stage)
    await service.change_stage(db, lead, stage, lost_reason=body.lost_reason, actor_id=user.id)
    await db.flush()
    await db.refresh(lead)
    return await service.to_out(db, lead, stage)


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_lead(
    lead: Lead = Depends(load_lead),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> None:
    await _require(db, user, workspace_id, lead.project_id, Perm.LEAD_DELETE)
    lead.deleted_at = datetime.now(UTC)
    await service.record_event(db, lead, "lead.deleted", actor_id=user.id)
    await db.flush()


@router.get("/leads/{lead_id}/events", response_model=list[LeadEventOut])
async def lead_events(
    lead: Lead = Depends(load_lead), db: AsyncSession = DbSession
) -> list[LeadEvent]:
    stmt = (
        select(LeadEvent)
        .where(LeadEvent.lead_id == lead.id)
        .order_by(LeadEvent.created_at, LeadEvent.id)
    )
    return list((await db.scalars(stmt)).all())


@router.post("/leads/{lead_id}/comments", response_model=LeadEventOut, status_code=201)
async def comment_lead(
    body: LeadComment,
    lead: Lead = Depends(load_lead),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> LeadEvent:
    await _require(db, user, workspace_id, lead.project_id, Perm.LEAD_MANAGE)
    ev = LeadEvent(
        workspace_id=lead.workspace_id,
        lead_id=lead.id,
        actor_id=user.id,
        action="comment",
        data={"text": body.text},
    )
    db.add(ev)
    await db.flush()
    return ev


@router.post("/leads/{lead_id}/task", response_model=LeadOut, status_code=201)
async def create_lead_task(
    body: LeadTaskCreate,
    lead: Lead = Depends(load_lead),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = DbSession,
) -> LeadOut:
    """Работа по лиду (аудит, КП, проверка) это задача того же проекта со ссылкой
    в обе стороны. У лида одна связанная задача; повторный вызов даёт 409."""
    await _require(db, user, workspace_id, lead.project_id, Perm.LEAD_MANAGE)
    await _require(db, user, workspace_id, lead.project_id, Perm.TASK_CREATE)
    if lead.task_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Lead already has a task")
    try:
        priority = Priority(body.priority).value
    except ValueError:
        raise HTTPException(422, "unknown priority") from None
    if body.assignee_id is not None and not await perms.has_project_permission(
        db, body.assignee_id, workspace_id, lead.project_id, Perm.TASK_VIEW
    ):
        raise HTTPException(422, "assignee has no project access")
    project = await db.get(Project, lead.project_id)
    type_id = await task_service._default_type_id(db, project.id)
    status_id = await task_service._default_status_id(db, project.id)
    if type_id is None or status_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Project has no task types or statuses")
    task = await task_service.create_task(
        db,
        project=project,
        reporter_id=user.id,
        title=body.title or f"Лид {lead.key}: {lead.title}"[:500],
        description=f"Лид: {_lead_url(lead)}",
        type_id=type_id,
        status_id=status_id,
        priority=priority,
        assignee_id=body.assignee_id,
        reviewer_id=None,
        parent_id=None,
        initiative_id=None,
        sprint_id=None,
        acceptance_criteria=None,
        definition_of_done=None,
        story_points=None,
        start_at=None,
        due_at=None,
    )
    lead.task_id = task.id
    await service.record_event(
        db, lead, "task.linked", actor_id=user.id, data={"task_key": task.key}
    )
    await db.flush()
    await db.refresh(lead)
    return await service.to_out(db, lead)


# -------------------------------------------------------------- ingest


async def _ingest_token(
    db: AsyncSession, x_lead_token: str | None
) -> tuple[LeadIngestToken, Project]:
    if not x_lead_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Lead-Token header is required")
    token = await db.scalar(
        select(LeadIngestToken).where(
            LeadIngestToken.token_hash == service.hash_token(x_lead_token.strip())
        )
    )
    if token is None or token.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked token")
    project = await db.get(Project, token.project_id)
    if project is None or project.archived_at is not None or not project.leads_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Leads are not enabled for this project")
    token.last_used_at = datetime.now(UTC)
    return token, project


@router.post("/ingest/leads", response_model=LeadIngestOut)
async def ingest_lead(
    body: LeadIngest,
    x_lead_token: str | None = Header(default=None),
    db: AsyncSession = DbSession,
) -> LeadIngestOut:
    """Приём лида по ключу проекта (вебхук формы, адаптер площадки).

    Идемпотентно по (source, external_id): повтор не создаёт дубль, а пишет
    событие `ingest.repeat`; если в повторе есть `stage`, этап меняется, а при
    `update=true` применяются присланные поля. Свои поля проверяются мягко:
    то, что не подошло под схему, сохраняется в `data._extra`, лид не теряется.
    """
    token, project = await _ingest_token(db, x_lead_token)
    project_fields = await service.fields(db, project.id)
    payload = body.model_dump(exclude_unset=True, exclude={"update", "stage", "lost_reason"})

    existing = None
    if body.external_id:
        existing = await db.scalar(
            select(Lead).where(
                Lead.project_id == project.id,
                Lead.source == body.source,
                Lead.external_id == body.external_id,
            )
        )
    if existing is not None and existing.deleted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Lead {existing.key} with this external_id was deleted"
        )
    if existing is not None:
        lead = existing
        if body.update:
            if body.data is not None:
                lead.data = service.clean_data(
                    project_fields, body.data, strict=False, current=lead.data
                )
            for field in (*_LEAD_SCALARS, "title"):
                if field in payload and payload[field] is not None:
                    setattr(lead, field, payload[field])
        await service.record_event(
            db, lead, "ingest.repeat", token_id=token.id,
            data={"updated": body.update, "fields": sorted(payload)},
        )
        if body.stage:
            stage = await service.stage_by_ref(db, project.id, None, body.stage)
            await service.change_stage(
                db, lead, stage, lost_reason=body.lost_reason, token_id=token.id
            )
        await db.flush()
        await db.refresh(lead)
        stage = await db.get(LeadStage, lead.stage_id)
        return LeadIngestOut(
            id=lead.id, key=lead.key, url=_lead_url(lead), created=False, stage_name=stage.name
        )

    stage = (
        await service.stage_by_ref(db, project.id, None, body.stage)
        if body.stage
        else await service.first_open_stage(db, project.id)
    )
    if stage.category == LeadStageCategory.LOST and not body.lost_reason:
        raise HTTPException(
            422, "lost_reason is required for a LOST stage"
        )
    data = service.clean_data(project_fields, body.data, strict=False)
    title = (
        body.title
        or body.contact_name
        or body.email
        or body.phone
        or f"Заявка {body.source}"
    )[:500]
    values = {k: payload.get(k) for k in (*_LEAD_SCALARS, "source", "external_id", "received_at")}
    values["source"] = body.source
    if stage.category == LeadStageCategory.LOST:
        values["lost_reason"] = body.lost_reason
    try:
        async with db.begin_nested():
            lead = await service.create_lead(
                db, project=project, stage=stage, title=title, values=values, data=data,
                actor_id=None, token_id=token.id, event_data={"via": token.label},
            )
    except IntegrityError:
        # два одинаковых вебхука одновременно: второй проиграл гонку, отдаём первый
        lead = await db.scalar(
            select(Lead).where(
                Lead.project_id == project.id,
                Lead.source == body.source,
                Lead.external_id == body.external_id,
            )
        )
        if lead is None:
            raise
        await service.record_event(db, lead, "ingest.repeat", token_id=token.id, data={})
        await db.flush()
        current = await db.get(LeadStage, lead.stage_id)
        return LeadIngestOut(
            id=lead.id, key=lead.key, url=_lead_url(lead), created=False,
            stage_name=current.name,
        )
    return LeadIngestOut(
        id=lead.id, key=lead.key, url=_lead_url(lead), created=True, stage_name=stage.name
    )
