"""Инбокс: приём входящего, видимость и разбор по шести исходам (решение P-002)."""

import pytest
from sqlalchemy import select

from app.models.enums import ProjectRole, SystemRole
from app.models.notification import Notification
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _setup(client, session, code="INB"):
    ws = await make_workspace(session)
    owner = await make_user(session, ws, "owner@inb.ex", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@inb.ex")
    r = await client.post("/projects", headers=_auth(tok), json={"name": "P", "code": code})
    assert r.status_code == 201, r.text
    return ws, owner, tok, r.json()


async def _member(client, session, ws, tok, proj, email, role=ProjectRole.MEMBER):
    user = await make_user(session, ws, email, SystemRole.MEMBER)
    await session.commit()
    r = await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(tok),
        json={"user_id": str(user.id), "role": role.value},
    )
    assert r.status_code in (200, 201), r.text
    return user, await _token(client, email)


async def _capture(client, tok, proj, title="Отчёт за октябрь", **extra):
    r = await client.post(
        f"/projects/{proj['id']}/inbox",
        headers=_auth(tok),
        json={"title": title, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Приём
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_captured_item_is_not_a_task_and_not_on_the_board(client, session):
    """Сырьё лежит в инбоксе и доску не засоряет: задач в проекте по-прежнему ноль."""
    _, _, tok, proj = await _setup(client, session)
    item = await _capture(client, tok, proj, source="telegram", url="https://t.me/c/1/2")

    assert item["status"] == "NEW"
    assert item["outcome"] is None
    assert item["task_id"] is None
    assert item["project_code"] == proj["code"]

    r = await client.get(f"/projects/{proj['id']}/tasks", headers=_auth(tok))
    assert r.json() == []
    r = await client.get(f"/projects/{proj['id']}/board", headers=_auth(tok))
    assert sum(len(c["tasks"]) for c in r.json()["columns"]) == 0


@pytest.mark.asyncio
async def test_repeat_with_same_external_id_does_not_double_the_queue(client, session):
    """Отчёт, прогнанный дважды, не даёт двух пунктов разбора."""
    _, _, tok, proj = await _setup(client, session)
    first = await _capture(client, tok, proj, source="report", external_id="oct-2026")
    again = await _capture(
        client, tok, proj, title="Он же, другими словами", source="report", external_id="oct-2026"
    )
    assert again["id"] == first["id"]
    assert again["title"] == first["title"]

    r = await client.get("/inbox", headers=_auth(tok))
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_personal_item_needs_no_project_and_stays_personal(client, session):
    """Мысль «из головы» пишется без проекта и видна только автору."""
    ws, _, tok, proj = await _setup(client, session)
    _, other_tok = await _member(client, session, ws, tok, proj, "member@inb.ex")

    r = await client.post("/inbox", headers=_auth(tok), json={"title": "Перечитать ТЗ §76"})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["project_id"] is None

    assert [i["id"] for i in (await client.get("/inbox", headers=_auth(tok))).json()] == [
        item["id"]
    ]
    assert (await client.get("/inbox", headers=_auth(other_tok))).json() == []
    r = await client.get(f"/inbox/{item['id']}", headers=_auth(other_tok))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_addressed_item_notifies_quietly_in_pms(client, session):
    """Адресату — отметка в PMS, а не прерывание: из «тебе положили» действие не следует."""
    ws, _, tok, proj = await _setup(client, session)
    member, member_tok = await _member(client, session, ws, tok, proj, "member@inb.ex")

    item = await _capture(client, tok, proj, title="Посмотри выгрузку", for_user_id=str(member.id))
    assert item["for_user_id"] == str(member.id)

    rows = (
        await session.scalars(select(Notification).where(Notification.user_id == member.id))
    ).all()
    assert [n.kind for n in rows] == ["inbox.captured"]

    r = await client.get("/inbox?mine_only=true", headers=_auth(member_tok))
    assert [i["id"] for i in r.json()] == [item["id"]]


@pytest.mark.asyncio
async def test_guest_does_not_see_the_project_inbox(client, session):
    """В инбоксе внутренняя переписка, а гость в проекте — обычно клиент."""
    ws, _, tok, proj = await _setup(client, session)
    await _capture(client, tok, proj)
    _, guest_tok = await _member(client, session, ws, tok, proj, "guest@inb.ex", ProjectRole.GUEST)

    assert (await client.get("/inbox", headers=_auth(guest_tok))).json() == []
    r = await client.post(
        f"/projects/{proj['id']}/inbox", headers=_auth(guest_tok), json={"title": "x"}
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Шесть исходов
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_did_it_myself_closes_without_a_task(client, session):
    """Сделал сам (меньше двух минут) — задачи не появляется, исход остаётся записанным."""
    _, owner, tok, proj = await _setup(client, session)
    item = await _capture(client, tok, proj)

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={"outcome": "DID", "note": "ответил в чате"},
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert (done["status"], done["outcome"]) == ("RESOLVED", "DID")
    assert done["task_id"] is None
    assert done["resolved_by_id"] == str(owner.id)
    assert (await client.get(f"/projects/{proj['id']}/tasks", headers=_auth(tok))).json() == []


@pytest.mark.asyncio
async def test_task_outcome_requires_its_own_next_action(client, session):
    """Заголовок сырья в задачу не копируется: действие формулируется на разборе."""
    _, _, tok, proj = await _setup(client, session)
    item = await _capture(
        client, tok, proj, title="Отчёт за октябрь — посмотреть, когда будет время"
    )

    r = await client.post(
        f"/inbox/{item['id']}/resolve", headers=_auth(tok), json={"outcome": "TASK"}
    )
    assert r.status_code == 422
    assert "title" in r.text

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={"outcome": "TASK", "title": "Сверить цифры отчёта с Метрикой", "priority": "HIGH"},
    )
    assert r.status_code == 200, r.text
    resolved = r.json()
    assert resolved["task_key"].startswith(f"{proj['code']}-")

    tasks = (await client.get(f"/projects/{proj['id']}/tasks", headers=_auth(tok))).json()
    assert [t["title"] for t in tasks] == ["Сверить цифры отчёта с Метрикой"]
    # контекст не теряется: откуда взялось, видно в описании задачи
    assert "Отчёт за октябрь" in tasks[0]["description"]
    assert tasks[0]["priority"] == "HIGH"


@pytest.mark.asyncio
async def test_delegated_outcome_needs_someone_and_tells_them(client, session):
    """Делегировать можно только кому-то, и он должен об этом узнать."""
    ws, _, tok, proj = await _setup(client, session)
    member, _ = await _member(client, session, ws, tok, proj, "member@inb.ex")
    item = await _capture(client, tok, proj, title="Клиент просит правки на лендинге")

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={"outcome": "DELEGATED", "title": "Внести правки клиента"},
    )
    assert r.status_code == 422
    assert "assignee_id" in r.text

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={
            "outcome": "DELEGATED",
            "title": "Внести правки клиента",
            "assignee_id": str(member.id),
        },
    )
    assert r.status_code == 200, r.text

    tasks = (await client.get(f"/projects/{proj['id']}/tasks", headers=_auth(tok))).json()
    assert tasks[0]["assignee_id"] == str(member.id)
    kinds = [
        n.kind
        for n in (
            await session.scalars(select(Notification).where(Notification.user_id == member.id))
        ).all()
    ]
    assert "task.assigned" in kinds


@pytest.mark.asyncio
async def test_calendar_outcome_demands_a_commitment_date(client, session):
    """В календарь — только с датой: календарь, где половину можно не делать, не календарь."""
    _, _, tok, proj = await _setup(client, session)
    item = await _capture(client, tok, proj, title="Разобрать и отправить отчёт")

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={"outcome": "CALENDAR", "title": "Разбор и отправка отчёта, 40 мин"},
    )
    assert r.status_code == 422
    assert "start_at" in r.text

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={
            "outcome": "CALENDAR",
            "title": "Разбор и отправка отчёта, 40 мин",
            "start_at": "2026-11-05T10:00:00+03:00",
        },
    )
    assert r.status_code == 200, r.text

    tasks = (await client.get(f"/projects/{proj['id']}/tasks", headers=_auth(tok))).json()
    assert tasks[0]["start_at"] is not None
    # обязательство на момент — это и срок: задача не бывает «на четверг» и без срока
    assert tasks[0]["due_at"] == tasks[0]["start_at"]


@pytest.mark.asyncio
async def test_reference_outcome_must_land_somewhere(client, session):
    """Справка без места — это та же неразобранная мысль."""
    _, _, tok, proj = await _setup(client, session)
    item = await _capture(client, tok, proj, title="Антон прислал правила редполитики")

    r = await client.post(
        f"/inbox/{item['id']}/resolve", headers=_auth(tok), json={"outcome": "REFERENCE"}
    )
    assert r.status_code == 422

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={"outcome": "REFERENCE", "reference_url": "https://wiki/projects/ssk/edpol"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reference_url"] == "https://wiki/projects/ssk/edpol"
    assert r.json()["task_id"] is None


@pytest.mark.asyncio
async def test_trash_outcome_is_recorded_not_erased(client, session):
    """«В мусор» — это исход, а не удаление: видно, чем кончилось входящее."""
    _, _, tok, proj = await _setup(client, session)
    item = await _capture(client, tok, proj, title="Рассылка про вебинар")

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={"outcome": "TRASH", "note": "реклама"},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["outcome"], r.json()["outcome_note"]) == ("TRASH", "реклама")

    assert (await client.get("/inbox", headers=_auth(tok))).json() == []
    r = await client.get("/inbox?status=RESOLVED", headers=_auth(tok))
    assert [i["outcome"] for i in r.json()] == ["TRASH"]


@pytest.mark.asyncio
async def test_resolving_twice_is_a_conflict(client, session):
    """Исход пишется один раз: иначе «чем кончилось» перестаёт быть ответом."""
    _, _, tok, proj = await _setup(client, session)
    item = await _capture(client, tok, proj)
    for expected in (200, 409):
        r = await client.post(
            f"/inbox/{item['id']}/resolve", headers=_auth(tok), json={"outcome": "DID"}
        )
        assert r.status_code == expected, r.text

    r = await client.patch(
        f"/inbox/{item['id']}", headers=_auth(tok), json={"title": "переписать"}
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_personal_item_gets_its_project_at_resolve(client, session):
    """Пункт без проекта обретает его на разборе — тогда же, когда появляется задача."""
    _, _, tok, proj = await _setup(client, session)
    r = await client.post("/inbox", headers=_auth(tok), json={"title": "Запинить зависимости"})
    item = r.json()

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={"outcome": "TASK", "title": "Запинить версии бэкенда в requirements"},
    )
    assert r.status_code == 422  # проекта нет ни в пункте, ни в запросе

    r = await client.post(
        f"/inbox/{item['id']}/resolve",
        headers=_auth(tok),
        json={
            "outcome": "TASK",
            "title": "Запинить версии бэкенда в requirements",
            "project_id": proj["id"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["project_id"] == proj["id"]


# --------------------------------------------------------------------------- #
# Счётчик
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_count_shows_only_what_waits_for_a_decision(client, session):
    """Счётчик для навигации и дайджеста: пустой инбокс — достижимое состояние."""
    _, _, tok, proj = await _setup(client, session)
    first = await _capture(client, tok, proj, title="Раз")
    await _capture(client, tok, proj, title="Два")
    await client.post("/inbox", headers=_auth(tok), json={"title": "Личное"})

    r = await client.get("/inbox/count", headers=_auth(tok))
    assert r.status_code == 200, r.text
    count = r.json()
    assert count["new"] == 3
    by_code = {c["project_code"]: c["new"] for c in count["by_project"]}
    assert by_code == {proj["code"]: 2, None: 1}

    await client.post(
        f"/inbox/{first['id']}/resolve", headers=_auth(tok), json={"outcome": "TRASH"}
    )
    assert (await client.get("/inbox/count", headers=_auth(tok))).json()["new"] == 2
