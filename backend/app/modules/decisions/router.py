"""Реестр решений в PMS: синк копии из вики и чтение (решение _global:P-022).

Правка решений идёт только в вике (`decisions.py`), сюда реестр приезжает
целиком (`PUT /decisions/sync`). Видимость: решение проекта видит тот, кто видит
проект; `_global` (кросс-проектные правила владельца) только владелец и админы
workspace.
"""

import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Text, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_workspace_id, load_project
from app.models.decision import Decision
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.modules.decisions.schemas import (
    DecisionDetail,
    DecisionOut,
    DecisionsSync,
    DecisionsSyncOut,
    DecisionTask,
    RegistrySynced,
)
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm

router = APIRouter(tags=["decisions"])

GLOBAL_REGISTRY = "_global"
GLOBAL_PREFIX = "G"
_GLOBAL_ALIASES = {"g", "_global", "global"}

_REF_RE = re.compile(r"^(?P<prefix>.+?)-(?P<letter>[A-Za-z])-(?P<num>\d{1,4})$")
# ключи задач в тексте `source`: «https://pms.klientlab.ru/t/kl-226», «SSK-203»
_TASK_KEY_RE = re.compile(r"(?<![\w-])([A-Za-z]{2,10}-\d{1,6})(?![\w-])")

_ITEM_FIELDS = (
    "area",
    "area_title",
    "status",
    "question",
    "decision",
    "decided_by",
    "decided_on",
    "source",
    "applies",
    "supersedes",
    "superseded_by",
    "keys",
    "aliases",
)


def _norm_ref(letter: str, num: str) -> str:
    return f"{letter.upper()}-{int(num):03d}"


def _task_keys(source: str | None, explicit: list[str]) -> list[str]:
    keys = [k.strip().upper() for k in explicit if k.strip()]
    for m in _TASK_KEY_RE.finditer(source or ""):
        key = m.group(1).upper()
        # «P-030» сюда не попадёт (одна буква), а «ID-3» или «UC-001» могут:
        # в выдачу уходят только реально существующие задачи, см. _tasks()
        if key not in keys:
            keys.append(key)
    return keys


def _out(d: Decision, project_code: str | None) -> DecisionOut:
    prefix = project_code if d.project_id else GLOBAL_PREFIX
    return DecisionOut(
        id=d.id,
        registry=d.registry,
        project_id=d.project_id,
        project_code=project_code,
        ref=d.ref,
        full_ref=f"{prefix}-{d.ref}",
        area=d.area,
        area_title=d.area_title,
        status=d.status,
        question=d.question,
        decision=d.decision,
        decided_by=d.decided_by,
        decided_on=d.decided_on,
        source=d.source,
        applies=d.applies,
        supersedes=d.supersedes,
        superseded_by=d.superseded_by,
        keys=list(d.keys or []),
        aliases=list(d.aliases or []),
        task_keys=list(d.task_keys or []),
        synced_at=d.synced_at,
    )


async def _can_see(db: AsyncSession, user: User, workspace_id: UUID, d: Decision) -> bool:
    if d.project_id is None:
        return await perms.has_workspace_permission(
            db, user.id, workspace_id, Perm.WORKSPACE_MANAGE
        )
    return await perms.has_project_permission(
        db, user.id, workspace_id, d.project_id, Perm.PROJECT_VIEW
    )


async def _codes(db: AsyncSession, project_ids: set[UUID]) -> dict[UUID, str]:
    if not project_ids:
        return {}
    rows = await db.execute(select(Project.id, Project.code).where(Project.id.in_(project_ids)))
    return {pid: code for pid, code in rows.all()}


def _filter(stmt, q: str | None, status_: str | None, area: str | None):
    if status_:
        stmt = stmt.where(Decision.status == status_)
    if area:
        stmt = stmt.where(Decision.area == area)
    if q:
        for word in q.split():
            like = f"%{word}%"
            stmt = stmt.where(
                or_(
                    Decision.ref.ilike(like),
                    Decision.question.ilike(like),
                    Decision.decision.ilike(like),
                    Decision.source.ilike(like),
                    cast(Decision.keys, Text).ilike(like),
                    cast(Decision.aliases, Text).ilike(like),
                )
            )
    return stmt.order_by(Decision.area, Decision.ref)


# ------------------------------------------------------------------ sync


@router.put("/decisions/sync", response_model=DecisionsSyncOut)
async def sync_decisions(
    body: DecisionsSync,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> DecisionsSyncOut:
    """Принять реестры из вики целиком: каждый присланный реестр заменяет свою
    копию (новые записи создаются, изменённые обновляются, пропавшие удаляются).
    Реестры, которых нет в запросе, не трогаются."""
    if not await perms.has_workspace_permission(db, user.id, workspace_id, Perm.WORKSPACE_MANAGE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Missing permission: {Perm.WORKSPACE_MANAGE}"
        )

    now = datetime.now(UTC)
    result: list[RegistrySynced] = []
    for reg in body.registries:
        project_id: UUID | None = None
        if reg.registry != GLOBAL_REGISTRY:
            if not reg.project_code:
                result.append(RegistrySynced(
                    registry=reg.registry, project_code=None, total=len(reg.items),
                    created=0, updated=0, deleted=0, skipped="no project_code",
                ))
                continue
            project_id = await db.scalar(
                select(Project.id).where(
                    Project.workspace_id == workspace_id,
                    func.upper(Project.code) == reg.project_code.strip().upper(),
                )
            )
            if project_id is None:
                result.append(RegistrySynced(
                    registry=reg.registry, project_code=reg.project_code, total=len(reg.items),
                    created=0, updated=0, deleted=0, skipped="project not found",
                ))
                continue

        existing = {
            d.ref: d
            for d in (
                await db.scalars(
                    select(Decision).where(
                        Decision.workspace_id == workspace_id, Decision.registry == reg.registry
                    )
                )
            ).all()
        }
        created = updated = 0
        seen: set[str] = set()
        for item in reg.items:
            m = re.match(r"^([A-Za-z])-(\d{1,4})$", item.ref.strip())
            if not m:
                raise HTTPException(
                    422,
                    f"{reg.registry}: bad ref {item.ref!r}",
                )
            ref = _norm_ref(*m.groups())
            if ref in seen:
                raise HTTPException(
                    422, f"{reg.registry}: duplicate ref {ref}"
                )
            seen.add(ref)
            values = {f: getattr(item, f) for f in _ITEM_FIELDS}
            values["task_keys"] = _task_keys(item.source, item.tasks)
            d = existing.get(ref)
            if d is None:
                db.add(Decision(
                    workspace_id=workspace_id, project_id=project_id, registry=reg.registry,
                    ref=ref, synced_at=now, **values,
                ))
                created += 1
                continue
            changed = d.project_id != project_id or any(
                getattr(d, f) != v for f, v in values.items()
            )
            if changed:
                for f, v in values.items():
                    setattr(d, f, v)
                d.project_id = project_id
                d.synced_at = now
                updated += 1
        gone = [ref for ref in existing if ref not in seen]
        if gone:
            await db.execute(
                delete(Decision).where(
                    Decision.workspace_id == workspace_id,
                    Decision.registry == reg.registry,
                    Decision.ref.in_(gone),
                )
            )
        result.append(RegistrySynced(
            registry=reg.registry, project_code=reg.project_code, total=len(reg.items),
            created=created, updated=updated, deleted=len(gone),
        ))
    await db.flush()
    return DecisionsSyncOut(registries=result)


# ------------------------------------------------------------------ read


@router.get("/projects/{project_id}/decisions", response_model=list[DecisionOut])
async def list_project_decisions(
    project: Project = Depends(load_project),
    q: str | None = Query(default=None, max_length=200),
    status_: str | None = Query(default=None, alias="status", max_length=20),
    area: str | None = Query(default=None, max_length=40),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionOut]:
    stmt = _filter(select(Decision).where(Decision.project_id == project.id), q, status_, area)
    return [_out(d, project.code) for d in (await db.scalars(stmt)).all()]


@router.get("/decisions/global", response_model=list[DecisionOut])
async def list_global_decisions(
    q: str | None = Query(default=None, max_length=200),
    status_: str | None = Query(default=None, alias="status", max_length=20),
    area: str | None = Query(default=None, max_length=40),
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionOut]:
    if not await perms.has_workspace_permission(db, user.id, workspace_id, Perm.WORKSPACE_MANAGE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    stmt = _filter(
        select(Decision).where(
            Decision.workspace_id == workspace_id, Decision.registry == GLOBAL_REGISTRY
        ),
        q, status_, area,
    )
    return [_out(d, None) for d in (await db.scalars(stmt)).all()]


async def _tasks(
    db: AsyncSession, user: User, workspace_id: UUID, keys: list[str]
) -> list[DecisionTask]:
    if not keys:
        return []
    rows = (
        await db.execute(
            select(Task, TaskStatus)
            .join(TaskStatus, TaskStatus.id == Task.status_id)
            .where(
                Task.workspace_id == workspace_id,
                func.upper(Task.key).in_([k.upper() for k in keys]),
                Task.deleted_at.is_(None),
            )
        )
    ).all()
    by_key = {}
    allowed: dict[UUID, bool] = {}
    for task, st in rows:
        if task.project_id not in allowed:
            allowed[task.project_id] = await perms.has_project_permission(
                db, user.id, workspace_id, task.project_id, Perm.TASK_VIEW
            )
        if allowed[task.project_id]:
            by_key[task.key.upper()] = DecisionTask(
                key=task.key, title=task.title, status_name=st.name, status_category=st.category
            )
    return [by_key[k.upper()] for k in keys if k.upper() in by_key]


@router.get("/decisions/by-ref/{full_ref}", response_model=DecisionDetail)
async def get_decision(
    full_ref: str,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> DecisionDetail:
    """Решение по ссылке `/d/<префикс>-<номер>`: префикс это код проекта PMS
    (`SSK`), имя реестра в вике (`skolkoskolko`) или `G` для `_global`."""
    m = _REF_RE.match(full_ref.strip())
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    prefix = m.group("prefix")
    ref = _norm_ref(m.group("letter"), m.group("num"))

    stmt = select(Decision).where(Decision.workspace_id == workspace_id, Decision.ref == ref)
    if prefix.lower() in _GLOBAL_ALIASES:
        stmt = stmt.where(Decision.registry == GLOBAL_REGISTRY)
    else:
        project_id = await db.scalar(
            select(Project.id).where(
                Project.workspace_id == workspace_id,
                func.upper(Project.code) == prefix.upper(),
            )
        )
        stmt = stmt.where(
            Decision.project_id == project_id
            if project_id is not None
            else Decision.registry == prefix.lower()
        )
    d = await db.scalar(stmt)
    if d is None or not await _can_see(db, user, workspace_id, d):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    codes = await _codes(db, {d.project_id} if d.project_id else set())
    out = _out(d, codes.get(d.project_id) if d.project_id else None)
    return DecisionDetail(
        **out.model_dump(), tasks=await _tasks(db, user, workspace_id, out.task_keys)
    )


@router.get("/decisions/by-task/{key}", response_model=list[DecisionOut])
async def decisions_for_task(
    key: str,
    user: User = Depends(get_current_user),
    workspace_id: UUID = Depends(get_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionOut]:
    """Решения, которые ссылаются на задачу (поле `tasks` или ссылка в `source`)."""
    rows = (
        await db.scalars(
            select(Decision)
            .where(
                Decision.workspace_id == workspace_id,
                Decision.task_keys.contains([key.strip().upper()]),
            )
            .order_by(Decision.registry, Decision.ref)
        )
    ).all()
    visible = [d for d in rows if await _can_see(db, user, workspace_id, d)]
    codes = await _codes(db, {d.project_id for d in visible if d.project_id})
    return [_out(d, codes.get(d.project_id) if d.project_id else None) for d in visible]
