"""Логика модуля «Лиды»: засев воронки, проверка своих полей, этапы, статистика."""

import hashlib
import re
import secrets
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadFieldType, LeadStageCategory
from app.models.lead import Lead, LeadEvent, LeadField, LeadStage
from app.models.project import Project
from app.models.task import Task
from app.modules.leads.presets import PRESETS
from app.modules.leads.schemas import LeadOut

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOKEN_PREFIX = "pl_"


# ------------------------------------------------------------------ tokens


def new_token() -> tuple[str, str, str]:
    """(значение, sha256, префикс для показа)."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_token(raw), raw[:10]


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ------------------------------------------------------------- settings


async def stages(db: AsyncSession, project_id: UUID) -> list[LeadStage]:
    stmt = (
        select(LeadStage)
        .where(LeadStage.project_id == project_id)
        .order_by(LeadStage.position, LeadStage.created_at)
    )
    return list((await db.scalars(stmt)).all())


async def fields(db: AsyncSession, project_id: UUID) -> list[LeadField]:
    stmt = (
        select(LeadField)
        .where(LeadField.project_id == project_id)
        .order_by(LeadField.position, LeadField.created_at)
    )
    return list((await db.scalars(stmt)).all())


async def seed_preset(db: AsyncSession, project: Project, preset: str) -> None:
    """Засевает этапы и поля, только если у проекта их ещё нет: повторное
    включение после выключения не плодит копии и не трогает правки владельца."""
    spec = PRESETS[preset]
    if not await stages(db, project.id):
        for i, (name, category, color) in enumerate(spec["stages"]):
            db.add(
                LeadStage(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    name=name,
                    category=category,
                    position=(i + 1) * 10,
                    color=color,
                )
            )
    if not await fields(db, project.id):
        for i, f in enumerate(spec["fields"]):
            db.add(
                LeadField(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    key=f["key"],
                    label=f["label"],
                    type=f["type"],
                    options=f.get("options"),
                    required=f.get("required", False),
                    is_pii=f.get("is_pii", False),
                    position=(i + 1) * 10,
                )
            )
    await db.flush()


def require_enabled(project: Project) -> None:
    if not project.leads_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leads are not enabled for this project")


# --------------------------------------------------------- field values


def _coerce(field: LeadField, value: Any) -> Any:
    """Приводит значение к типу поля или бросает ValueError."""
    if value is None or value == "":
        return None
    t = field.type
    if t in (LeadFieldType.TEXT, LeadFieldType.PHONE):
        return str(value).strip()
    if t == LeadFieldType.NUMBER:
        if isinstance(value, bool):
            raise ValueError("number expected")
        num = float(value)
        return int(num) if num.is_integer() else num
    if t == LeadFieldType.MONEY:
        try:
            return str(Decimal(str(value)).quantize(Decimal("0.01")))
        except InvalidOperation:
            raise ValueError("money expected") from None
    if t == LeadFieldType.DATE:
        return date.fromisoformat(str(value)[:10]).isoformat()
    if t == LeadFieldType.DATETIME:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    if t == LeadFieldType.SELECT:
        v = str(value)
        if field.options and v not in field.options:
            raise ValueError(f"one of {field.options} expected")
        return v
    if t == LeadFieldType.EMAIL:
        v = str(value).strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("email expected")
        return v
    if t == LeadFieldType.URL:
        v = str(value).strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v
    return value


def clean_data(
    project_fields: list[LeadField],
    data: dict[str, Any] | None,
    *,
    strict: bool,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Проверяет значения своих полей.

    strict (пользователь, API): неизвестный ключ, неверный тип или пустое
    обязательное поле дают 422.
    не strict (приём по ключу): лид важнее схемы, поэтому всё, что не прошло
    проверку, складывается в `_extra` как есть, а обязательность не требуется.
    """
    by_key = {f.key: f for f in project_fields}
    result = dict(current or {})
    extra: dict[str, Any] = dict(result.get("_extra") or {})
    errors: dict[str, str] = {}

    for k, v in (data or {}).items():
        field = by_key.get(k)
        if field is None:
            if strict:
                errors[k] = "unknown field"
            else:
                extra[k] = v
            continue
        try:
            coerced = _coerce(field, v)
        except (ValueError, TypeError) as exc:
            if strict:
                errors[k] = str(exc) or "invalid value"
            else:
                extra[k] = v
            continue
        if coerced is None:
            result.pop(k, None)
        else:
            result[k] = coerced

    if strict:
        for f in project_fields:
            if f.required and result.get(f.key) in (None, ""):
                errors.setdefault(f.key, "required")
    if errors:
        raise HTTPException(
            422, {"message": "invalid lead data", "fields": errors}
        )
    if extra:
        result["_extra"] = extra
    else:
        result.pop("_extra", None)
    return result


# ------------------------------------------------------------- leads


async def record_event(
    db: AsyncSession,
    lead: Lead,
    action: str,
    *,
    actor_id: UUID | None = None,
    token_id: UUID | None = None,
    data: dict | None = None,
) -> None:
    db.add(
        LeadEvent(
            workspace_id=lead.workspace_id,
            lead_id=lead.id,
            actor_id=actor_id,
            token_id=token_id,
            action=action,
            data=data,
        )
    )


async def first_open_stage(db: AsyncSession, project_id: UUID) -> LeadStage:
    for s in await stages(db, project_id):
        if s.category == LeadStageCategory.OPEN:
            return s
    raise HTTPException(status.HTTP_409_CONFLICT, "Project has no OPEN lead stage")


async def stage_by_ref(
    db: AsyncSession, project_id: UUID, stage_id: UUID | None, name: str | None
) -> LeadStage:
    if stage_id is not None:
        s = await db.get(LeadStage, stage_id)
        if s is None or s.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Stage belongs to another project")
        return s
    if name:
        wanted = name.strip().lower()
        for s in await stages(db, project_id):
            if s.name.lower() == wanted:
                return s
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown stage: {name}")
    raise HTTPException(422, "stage_id or stage is required")


async def create_lead(
    db: AsyncSession,
    *,
    project: Project,
    stage: LeadStage,
    title: str,
    values: dict[str, Any],
    data: dict[str, Any],
    actor_id: UUID | None,
    token_id: UUID | None = None,
    event_data: dict | None = None,
) -> Lead:
    # atomic, like task numbers: a parallel create waits on the project row lock
    number = await db.scalar(
        update(Project)
        .where(Project.id == project.id)
        .values(lead_counter=Project.lead_counter + 1)
        .returning(Project.lead_counter)
    )
    now = datetime.now(UTC)
    lead = Lead(
        workspace_id=project.workspace_id,
        project_id=project.id,
        number=number,
        key=f"{project.code}-L-{number}",
        title=title,
        stage_id=stage.id,
        data=data,
        received_at=values.pop("received_at", None) or now,
        closed_at=now if stage.category != LeadStageCategory.OPEN else None,
        created_by_id=actor_id,
        **{k: v for k, v in values.items() if v is not None},
    )
    db.add(lead)
    await db.flush()
    await record_event(
        db,
        lead,
        "lead.created",
        actor_id=actor_id,
        token_id=token_id,
        data={"stage": stage.name, **(event_data or {})},
    )
    return lead


async def change_stage(
    db: AsyncSession,
    lead: Lead,
    new: LeadStage,
    *,
    lost_reason: str | None,
    actor_id: UUID | None = None,
    token_id: UUID | None = None,
) -> None:
    if new.category == LeadStageCategory.LOST and not (lost_reason or lead.lost_reason):
        raise HTTPException(
            422, "lost_reason is required for a LOST stage"
        )
    if new.id == lead.stage_id:
        return
    old = await db.get(LeadStage, lead.stage_id)
    lead.stage_id = new.id
    if new.category == LeadStageCategory.OPEN:
        lead.closed_at = None
    elif lead.closed_at is None or (old is not None and old.category != new.category):
        lead.closed_at = datetime.now(UTC)
    if new.category == LeadStageCategory.LOST:
        lead.lost_reason = lost_reason or lead.lost_reason
    await record_event(
        db,
        lead,
        "stage.changed",
        actor_id=actor_id,
        token_id=token_id,
        data={
            "from": old.name if old else None,
            "from_id": str(old.id) if old else None,
            "to": new.name,
            "to_id": str(new.id),
            **({"lost_reason": lost_reason} if lost_reason else {}),
        },
    )


async def to_out(db: AsyncSession, lead: Lead, stage: LeadStage | None = None) -> LeadOut:
    stage = stage or await db.get(LeadStage, lead.stage_id)
    task_key = None
    if lead.task_id:
        task = await db.get(Task, lead.task_id)
        task_key = task.key if task and task.deleted_at is None else None
    return _out(lead, stage, task_key)


def _out(lead: Lead, stage: LeadStage, task_key: str | None) -> LeadOut:
    return LeadOut(
        id=lead.id,
        project_id=lead.project_id,
        key=lead.key,
        number=lead.number,
        title=lead.title,
        stage_id=lead.stage_id,
        stage_name=stage.name,
        stage_category=stage.category,
        owner_id=lead.owner_id,
        source=lead.source,
        source_url=lead.source_url,
        external_id=lead.external_id,
        contact_name=lead.contact_name,
        phone=lead.phone,
        email=lead.email,
        amount=lead.amount,
        currency=lead.currency,
        data=lead.data or {},
        received_at=lead.received_at,
        closed_at=lead.closed_at,
        lost_reason=lead.lost_reason,
        task_id=lead.task_id,
        task_key=task_key,
        duplicate_of_id=lead.duplicate_of_id,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


async def list_out(db: AsyncSession, leads: list[Lead], project_id: UUID) -> list[LeadOut]:
    by_id = {s.id: s for s in await stages(db, project_id)}
    task_ids = [lead.task_id for lead in leads if lead.task_id]
    task_keys: dict[UUID, str] = {}
    if task_ids:
        rows = await db.execute(
            select(Task.id, Task.key).where(Task.id.in_(task_ids), Task.deleted_at.is_(None))
        )
        task_keys = {tid: key for tid, key in rows.all()}
    return [
        _out(lead, by_id[lead.stage_id], task_keys.get(lead.task_id) if lead.task_id else None)
        for lead in leads
    ]


# ---------------------------------------------------------------- stats


async def stats(
    db: AsyncSession, project_id: UUID, period_from: datetime, period_to: datetime
) -> dict:
    stage_list = await stages(db, project_id)
    by_id = {s.id: s for s in stage_list}
    leads = list(
        (
            await db.scalars(
                select(Lead).where(
                    Lead.project_id == project_id,
                    Lead.deleted_at.is_(None),
                    Lead.received_at >= period_from,
                    Lead.received_at < period_to,
                )
            )
        ).all()
    )
    lead_ids = [lead.id for lead in leads]

    # где лиды побывали: начальный этап из события создания плюс все переходы
    reached: dict[UUID, set[UUID]] = defaultdict(set)
    if lead_ids:
        name_to_id = {s.name: s.id for s in stage_list}
        events = await db.scalars(
            select(LeadEvent).where(
                LeadEvent.lead_id.in_(lead_ids),
                LeadEvent.action.in_(("stage.changed", "lead.created")),
            )
        )
        for ev in events:
            d = ev.data or {}
            if ev.action == "stage.changed" and d.get("to_id"):
                reached[ev.lead_id].add(UUID(d["to_id"]))
            elif ev.action == "lead.created" and d.get("stage") in name_to_id:
                reached[ev.lead_id].add(name_to_id[d["stage"]])
    for lead in leads:
        reached[lead.id].add(lead.stage_id)

    zero = Decimal("0")
    stage_rows = []
    for s in stage_list:
        on_stage = [lead for lead in leads if lead.stage_id == s.id]
        stage_rows.append(
            {
                "stage_id": s.id,
                "name": s.name,
                "category": s.category,
                "count": len(on_stage),
                "reached": sum(1 for lead in leads if s.id in reached[lead.id]),
                "amount": sum((lead.amount or zero for lead in on_stage), zero),
            }
        )

    def cat(lead: Lead) -> str:
        return by_id[lead.stage_id].category

    won = [lead for lead in leads if cat(lead) == LeadStageCategory.WON]
    lost = [lead for lead in leads if cat(lead) == LeadStageCategory.LOST]
    open_ = [lead for lead in leads if cat(lead) == LeadStageCategory.OPEN]
    closed = [lead for lead in won + lost if lead.closed_at]
    avg_days = (
        sum((lead.closed_at - lead.received_at).total_seconds() for lead in closed)
        / len(closed)
        / 86400
        if closed
        else None
    )

    src: dict[str, dict] = {}
    for lead in leads:
        row = src.setdefault(
            lead.source, {"source": lead.source, "count": 0, "won": 0, "won_amount": zero}
        )
        row["count"] += 1
        if cat(lead) == LeadStageCategory.WON:
            row["won"] += 1
            row["won_amount"] += lead.amount or zero

    return {
        "period_from": period_from,
        "period_to": period_to,
        "total": len(leads),
        "open": len(open_),
        "won": len(won),
        "lost": len(lost),
        "win_rate": round(len(won) / (len(won) + len(lost)), 4) if (won or lost) else None,
        "open_amount": sum((lead.amount or zero for lead in open_), zero),
        "won_amount": sum((lead.amount or zero for lead in won), zero),
        "avg_days_to_close": round(avg_days, 2) if avg_days is not None else None,
        "stages": stage_rows,
        "sources": sorted(src.values(), key=lambda r: -r["count"]),
    }
