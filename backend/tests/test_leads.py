"""Модуль «Лиды»: включение на проекте, воронка, свои поля, приём по ключу, права."""

import pytest

from app.models.enums import ProjectRole, SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _owner_project(client, session, code="KL", preset="sales", enable=True):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    r = await client.post("/projects", headers=_auth(tok), json={"name": "P", "code": code})
    assert r.status_code == 201, r.text
    proj = r.json()
    assert proj["leads_enabled"] is False
    settings = None
    if enable:
        r = await client.post(
            f"/projects/{proj['id']}/leads/enable", headers=_auth(tok), json={"preset": preset}
        )
        assert r.status_code == 200, r.text
        settings = r.json()
    return ws, tok, proj, settings


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


def _stage(settings, name):
    return next(s for s in settings["stages"] if s["name"] == name)


@pytest.mark.asyncio
async def test_disabled_project_hides_leads(client, session):
    _, tok, proj, _ = await _owner_project(client, session, enable=False)
    r = await client.get(f"/projects/{proj['id']}/leads", headers=_auth(tok))
    assert r.status_code == 404
    r = await client.post(
        f"/projects/{proj['id']}/leads", headers=_auth(tok), json={"title": "x"}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_enable_seeds_preset_once(client, session):
    _, tok, proj, settings = await _owner_project(client, session, preset="orders", code="ORD")
    names = [s["name"] for s in settings["stages"]]
    assert names[0] == "Новый" and "Оплачен" in names and "Отменён" in names
    assert {f["key"] for f in settings["fields"]} >= {"platform", "pickup_at", "from", "to"}
    assert settings["tokens"] == []

    # выключили и включили снова другим пресетом: засев не дублируется
    pid = proj["id"]
    assert (await client.post(f"/projects/{pid}/leads/disable", headers=_auth(tok))).json()[
        "enabled"
    ] is False
    r = await client.post(
        f"/projects/{pid}/leads/enable", headers=_auth(tok), json={"preset": "sales"}
    )
    assert r.status_code == 200
    assert [s["name"] for s in r.json()["stages"]] == names

    r = await client.get(f"/projects/{pid}", headers=_auth(tok))
    assert r.json()["leads_enabled"] is True


@pytest.mark.asyncio
async def test_lead_lifecycle_and_stage_rules(client, session):
    _, tok, proj, settings = await _owner_project(client, session)
    pid = proj["id"]
    r = await client.post(
        f"/projects/{pid}/leads",
        headers=_auth(tok),
        json={
            "title": "Спецтехника, Kwork #3267289",
            "source": "kwork",
            "external_id": "3267289",
            "contact_name": "Артём",
            "amount": "15000",
            "data": {"budget": 100000, "site": "https://example.com", "leads_db_id": "8977"},
        },
    )
    assert r.status_code == 201, r.text
    lead = r.json()
    assert lead["key"] == "KL-L-1"
    assert lead["stage_name"] == "Новый"
    assert lead["data"] == {
        "budget": "100000.00", "site": "https://example.com", "leads_db_id": 8977
    }

    # тот же внешний id второй раз руками: конфликт, а не дубль
    r = await client.post(
        f"/projects/{pid}/leads", headers=_auth(tok),
        json={"title": "дубль", "source": "kwork", "external_id": "3267289"},
    )
    assert r.status_code == 409

    # неизвестное поле и кривой url в strict-режиме дают 422 с разбором по полям
    r = await client.patch(
        f"/leads/{lead['id']}", headers=_auth(tok), json={"data": {"nope": 1, "site": "example"}}
    )
    assert r.status_code == 422
    assert set(r.json()["detail"]["fields"]) == {"nope", "site"}

    # LOST без причины нельзя
    lost = _stage(settings, "Проигран")
    r = await client.patch(
        f"/leads/{lead['id']}/stage", headers=_auth(tok), json={"stage_id": lost["id"]}
    )
    assert r.status_code == 422

    r = await client.patch(
        f"/leads/{lead['id']}/stage", headers=_auth(tok), json={"stage": "переговоры"}
    )
    assert r.status_code == 200 and r.json()["stage_name"] == "Переговоры"
    assert r.json()["closed_at"] is None

    r = await client.patch(
        f"/leads/{lead['id']}/stage", headers=_auth(tok), json={"stage": "Выигран"}
    )
    assert r.json()["stage_category"] == "WON" and r.json()["closed_at"] is not None

    r = await client.post(
        f"/leads/{lead['id']}/comments", headers=_auth(tok), json={"text": "договор подписан"}
    )
    assert r.status_code == 201

    r = await client.get(f"/leads/{lead['id']}/events", headers=_auth(tok))
    actions = [e["action"] for e in r.json()]
    assert actions == ["lead.created", "stage.changed", "stage.changed", "comment"]

    r = await client.get("/leads/by-key/kl-l-1", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["id"] == lead["id"]


@pytest.mark.asyncio
async def test_board_and_stats(client, session):
    _, tok, proj, settings = await _owner_project(client, session)
    pid = proj["id"]
    ids = []
    for i, src in enumerate(["kwork", "kwork", "site"]):
        r = await client.post(
            f"/projects/{pid}/leads", headers=_auth(tok),
            json={"title": f"L{i}", "source": src, "amount": "10000"},
        )
        ids.append(r.json()["id"])
    await client.patch(f"/leads/{ids[0]}/stage", headers=_auth(tok), json={"stage": "Переговоры"})
    await client.patch(f"/leads/{ids[0]}/stage", headers=_auth(tok), json={"stage": "Выигран"})
    await client.patch(
        f"/leads/{ids[1]}/stage", headers=_auth(tok),
        json={"stage": "Проигран", "lost_reason": "выбрали другого"},
    )

    r = await client.get(f"/projects/{pid}/leads/board", headers=_auth(tok))
    cols = {c["stage"]["name"]: c for c in r.json()["columns"]}
    assert cols["Новый"]["count"] == 1 and cols["Выигран"]["count"] == 1
    assert cols["Проигран"]["leads"][0]["lost_reason"] == "выбрали другого"

    r = await client.get(f"/projects/{pid}/leads/stats", headers=_auth(tok))
    s = r.json()
    assert (s["total"], s["open"], s["won"], s["lost"]) == (3, 1, 1, 1)
    assert s["win_rate"] == 0.5
    assert s["won_amount"] == "10000.00"
    reached = {row["name"]: row["reached"] for row in s["stages"]}
    assert reached["Новый"] == 3 and reached["Переговоры"] == 1 and reached["Выигран"] == 1
    kwork = next(row for row in s["sources"] if row["source"] == "kwork")
    assert (kwork["count"], kwork["won"]) == (2, 1)

    r = await client.get(f"/projects/{pid}/leads?category=OPEN", headers=_auth(tok))
    assert [x["title"] for x in r.json()] == ["L2"]
    r = await client.get(f"/projects/{pid}/leads?q=L1", headers=_auth(tok))
    assert [x["title"] for x in r.json()] == ["L1"]


@pytest.mark.asyncio
async def test_ingest_token_dedup_and_soft_fields(client, session):
    _, tok, proj, _ = await _owner_project(client, session, code="ORD", preset="orders")
    pid = proj["id"]
    r = await client.post(
        f"/projects/{pid}/lead-tokens", headers=_auth(tok), json={"label": "UBO adapter"}
    )
    assert r.status_code == 201
    raw = r.json()["token"]
    assert raw.startswith("pl_") and r.json()["prefix"] == raw[:10]

    # ключ не отдаётся повторно в настройках
    r = await client.get(f"/projects/{pid}/leads/settings", headers=_auth(tok))
    assert "token" not in r.json()["tokens"][0]

    body = {
        "source": "ubo",
        "external_id": "1001",
        "contact_name": "Иван",
        "phone": "+7 900 000-00-00",
        "amount": "5400",
        "data": {"platform": "UBO", "pickup_at": "2026-10-20T09:30:00+03:00",
                 "from": "Внуково", "to": "Москва", "passengers": "2", "flight": "SU 1234"},
    }
    assert (await client.post("/ingest/leads", json=body)).status_code == 401
    assert (
        await client.post("/ingest/leads", json=body, headers={"X-Lead-Token": "pl_wrong"})
    ).status_code == 401

    h = {"X-Lead-Token": raw}
    r = await client.post("/ingest/leads", json=body, headers=h)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["created"] is True and first["key"] == "ORD-L-1"
    assert first["url"].endswith("/l/ord-l-1")

    # повтор того же заказа: не дубль; со stage меняет этап
    r = await client.post("/ingest/leads", json=body | {"stage": "Подтверждён"}, headers=h)
    assert r.json()["created"] is False and r.json()["id"] == first["id"]
    assert r.json()["stage_name"] == "Подтверждён"

    r = await client.get(f"/leads/{first['id']}", headers=_auth(tok))
    lead = r.json()
    assert lead["data"]["passengers"] == 2
    assert lead["data"]["_extra"] == {"flight": "SU 1234"}  # не по схеме, но не потеряно
    assert lead["phone"] == "+7 900 000-00-00"

    # update=true применяет поля повтора
    r = await client.post(
        "/ingest/leads", headers=h,
        json={"source": "ubo", "external_id": "1001", "amount": "6000", "update": True,
              "data": {"driver": "Пётр"}},
    )
    r = await client.get(f"/leads/{first['id']}", headers=_auth(tok))
    assert r.json()["amount"] == "6000.00" and r.json()["data"]["driver"] == "Пётр"
    assert r.json()["data"]["from"] == "Внуково"

    events = (await client.get(f"/leads/{first['id']}/events", headers=_auth(tok))).json()
    assert [e["action"] for e in events].count("ingest.repeat") == 2
    assert events[0]["token_id"] is not None and events[0]["actor_id"] is None

    # отозванный ключ и выключенный модуль закрывают приём
    tid = (await client.get(f"/projects/{pid}/leads/settings", headers=_auth(tok))).json()[
        "tokens"
    ][0]["id"]
    await client.post(f"/lead-tokens/{tid}/revoke", headers=_auth(tok))
    r = await client.post("/ingest/leads", json=body | {"external_id": "1002"}, headers=h)
    assert r.status_code == 401

    raw2 = (
        await client.post(f"/projects/{pid}/lead-tokens", headers=_auth(tok), json={"label": "2"})
    ).json()["token"]
    await client.post(f"/projects/{pid}/leads/disable", headers=_auth(tok))
    r = await client.post(
        "/ingest/leads", json=body | {"external_id": "1003"}, headers={"X-Lead-Token": raw2}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_lead_task_link(client, session):
    _, tok, proj, _ = await _owner_project(client, session)
    pid = proj["id"]
    lead = (
        await client.post(f"/projects/{pid}/leads", headers=_auth(tok), json={"title": "Аудит"})
    ).json()
    r = await client.post(f"/leads/{lead['id']}/task", headers=_auth(tok), json={})
    assert r.status_code == 201, r.text
    assert r.json()["task_key"] == "KL-1"
    task = (await client.get("/tasks/by-key/KL-1", headers=_auth(tok))).json()
    assert task["title"] == "Лид KL-L-1: Аудит"
    assert "/l/kl-l-1" in task["description"]
    r = await client.post(f"/leads/{lead['id']}/task", headers=_auth(tok), json={})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_permissions(client, session):
    ws, tok, proj, settings = await _owner_project(client, session)
    pid = proj["id"]
    lead = (
        await client.post(
            f"/projects/{pid}/leads", headers=_auth(tok),
            json={"title": "x", "phone": "+79110000000", "email": "a@b.ru"},
        )
    ).json()

    _, mtok = await _member(client, session, ws, tok, proj, "member@ex.com")
    # участник видит и ведёт лиды, контакты без маски
    r = await client.get(f"/leads/{lead['id']}", headers=_auth(mtok))
    assert r.status_code == 200 and r.json()["phone"] == "+79110000000"
    r = await client.patch(
        f"/leads/{lead['id']}/stage", headers=_auth(mtok), json={"stage": "Квалификация"}
    )
    assert r.status_code == 200
    # но не удаляет и не настраивает воронку
    assert (await client.delete(f"/leads/{lead['id']}", headers=_auth(mtok))).status_code == 403
    r = await client.post(
        f"/projects/{pid}/lead-stages", headers=_auth(mtok), json={"name": "Новый этап"}
    )
    assert r.status_code == 403
    r = await client.get(f"/projects/{pid}/leads/settings", headers=_auth(mtok))
    assert r.status_code == 200 and r.json()["tokens"] is None

    _, vtok = await _member(client, session, ws, tok, proj, "viewer@ex.com", ProjectRole.VIEWER)
    assert (await client.get(f"/leads/{lead['id']}", headers=_auth(vtok))).status_code == 404
    assert (await client.get(f"/projects/{pid}/leads", headers=_auth(vtok))).status_code == 403

    outsider = await make_user(session, ws, "out@ex.com", SystemRole.MEMBER)
    await session.commit()
    otok = await _token(client, "out@ex.com")
    r = await client.get(f"/leads/{lead['id']}", headers=_auth(otok))
    assert outsider and r.status_code == 404

    # менеджер удаляет (мягко): лид пропадает из списка
    _, mgr = await _member(client, session, ws, tok, proj, "mgr@ex.com", ProjectRole.MANAGER)
    assert (await client.delete(f"/leads/{lead['id']}", headers=_auth(mgr))).status_code == 204
    assert (await client.get(f"/projects/{pid}/leads", headers=_auth(tok))).json() == []


@pytest.mark.asyncio
async def test_stage_and_field_settings(client, session):
    _, tok, proj, settings = await _owner_project(client, session, preset="basic")
    pid = proj["id"]
    r = await client.post(
        f"/projects/{pid}/lead-stages", headers=_auth(tok), json={"name": "Счёт выставлен"}
    )
    assert r.status_code == 201 and r.json()["position"] == 50
    r = await client.post(
        f"/projects/{pid}/lead-stages", headers=_auth(tok), json={"name": "Новый"}
    )
    assert r.status_code == 409

    lead = (
        await client.post(f"/projects/{pid}/leads", headers=_auth(tok), json={"title": "x"})
    ).json()
    new_stage = _stage(settings, "Новый")
    # этап с лидами нельзя удалить и нельзя сменить ему категорию
    r = await client.delete(f"/lead-stages/{new_stage['id']}", headers=_auth(tok))
    assert r.status_code == 409
    r = await client.patch(
        f"/lead-stages/{new_stage['id']}", headers=_auth(tok), json={"category": "WON"}
    )
    assert r.status_code == 409
    r = await client.patch(
        f"/lead-stages/{new_stage['id']}", headers=_auth(tok), json={"name": "Входящий"}
    )
    assert r.status_code == 200 and r.json()["name"] == "Входящий"

    r = await client.post(
        f"/projects/{pid}/lead-fields", headers=_auth(tok),
        json={"key": "city", "label": "Город", "type": "select", "options": ["Москва", "СПб"],
              "required": True},
    )
    assert r.status_code == 201
    assert (
        await client.post(
            f"/projects/{pid}/lead-fields", headers=_auth(tok),
            json={"key": "bad", "label": "x", "type": "select"},
        )
    ).status_code == 422
    # обязательное поле требуется при strict-создании
    r = await client.post(f"/projects/{pid}/leads", headers=_auth(tok), json={"title": "y"})
    assert r.status_code == 422 and r.json()["detail"]["fields"] == {"city": "required"}
    r = await client.patch(
        f"/leads/{lead['id']}", headers=_auth(tok), json={"data": {"city": "Казань"}}
    )
    assert r.status_code == 422
    r = await client.patch(
        f"/leads/{lead['id']}", headers=_auth(tok), json={"data": {"city": "СПб"}}
    )
    assert r.status_code == 200 and r.json()["data"] == {"city": "СПб"}
