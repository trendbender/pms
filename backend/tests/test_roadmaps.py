"""Роадмап проекта: период, волны, метрики, что его держит, таймлайн портфеля."""

import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _owner(client, session, code="RM", email="owner@ex.com"):
    ws = await make_workspace(session)
    await make_user(session, ws, email, SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, email)
    r = await client.post("/projects", headers=_auth(tok), json={"name": "P", "code": code})
    assert r.status_code == 201, r.text
    return ws, tok, r.json()


async def _roadmap(client, tok, project_id, **extra):
    body = {
        "title": "Месяц 1",
        "period_start": "2026-10-28",
        "period_end": "2026-11-26",
        "status": "ACTIVE",
        **extra,
    }
    r = await client.post(
        f"/projects/{project_id}/roadmaps", headers=_auth(tok), json=body
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _statuses(client, tok, project_id):
    r = await client.get(f"/projects/{project_id}/statuses", headers=_auth(tok))
    return {s["category"]: s for s in r.json()}


@pytest.mark.asyncio
async def test_roadmap_crud_and_period_validation(client, session):
    _, tok, proj = await _owner(client, session, code="RM1")
    rm = await _roadmap(
        client,
        tok,
        proj["id"],
        goal="Техника, сниппеты, ссылки",
        scope_note="план из 14 пунктов согласован клиентом 27.10 (K-006)",
        agreed_on="2026-10-27",
        decision_ref="K-006",
        report_url="http://example.test/roadmap.html",
    )
    assert rm["project_code"] == "RM1"
    assert rm["status"] == "ACTIVE"
    assert rm["task_count"] == 0

    r = await client.get(f"/projects/{proj['id']}/roadmap", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["id"] == rm["id"]

    r = await client.patch(
        f"/roadmaps/{rm['id']}", headers=_auth(tok), json={"status": "COMPLETED"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "COMPLETED"

    # период не может кончаться раньше, чем начинается
    r = await client.post(
        f"/projects/{proj['id']}/roadmaps",
        headers=_auth(tok),
        json={"title": "X", "period_start": "2026-11-01", "period_end": "2026-10-01"},
    )
    assert r.status_code == 400
    r = await client.patch(
        f"/roadmaps/{rm['id']}", headers=_auth(tok), json={"period_end": "2026-01-01"}
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_waves_carry_task_progress(client, session):
    _, tok, proj = await _owner(client, session, code="RM2")
    rm = await _roadmap(client, tok, proj["id"])

    r = await client.post(
        f"/projects/{proj['id']}/initiatives",
        headers=_auth(tok),
        json={"name": "Неделя 1", "due_date": "2026-11-03", "roadmap_id": rm["id"]},
    )
    assert r.status_code == 201, r.text
    wave = r.json()
    assert wave["roadmap_id"] == rm["id"]

    tasks = []
    for title in ("краул прода", "canonical"):
        r = await client.post(
            "/tasks",
            headers=_auth(tok),
            json={"project_id": proj["id"], "title": title, "initiative_id": wave["id"]},
        )
        assert r.status_code == 201, r.text
        tasks.append(r.json())

    statuses = await _statuses(client, tok, proj["id"])
    r = await client.patch(
        f"/tasks/{tasks[0]['id']}/status",
        headers=_auth(tok),
        json={"status_id": statuses["DONE"]["id"]},
    )
    assert r.status_code == 200
    r = await client.patch(
        f"/tasks/{tasks[1]['id']}/status",
        headers=_auth(tok),
        json={"status_id": statuses["BLOCKED"]["id"], "reason": "ждём доступ к GSC"},
    )
    assert r.status_code == 200

    r = await client.get(f"/roadmaps/{rm['id']}", headers=_auth(tok))
    assert r.status_code == 200
    detail = r.json()
    assert detail["wave_count"] == 1
    assert (detail["task_count"], detail["done_count"], detail["blocked_count"]) == (2, 1, 1)
    assert [w["name"] for w in detail["waves"]] == ["Неделя 1"]
    assert detail["waves"][0]["done_count"] == 1
    assert {t["key"] for t in detail["waves"][0]["tasks"]} == {t["key"] for t in tasks}
    # то, что держит роадмап, не хранится, а выводится из задач
    assert [t["blocked_reason"] for t in detail["waiting"]] == ["ждём доступ к GSC"]


@pytest.mark.asyncio
async def test_wave_must_belong_to_the_same_project(client, session):
    _, tok, proj = await _owner(client, session, code="RM3")
    rm = await _roadmap(client, tok, proj["id"])
    r = await client.post("/projects", headers=_auth(tok), json={"name": "Other", "code": "OTH"})
    other = r.json()
    r = await client.post(
        f"/projects/{other['id']}/initiatives",
        headers=_auth(tok),
        json={"name": "Чужая волна", "roadmap_id": rm["id"]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_metrics_baseline_target_current(client, session):
    _, tok, proj = await _owner(client, session, code="RM4")
    rm = await _roadmap(client, tok, proj["id"])
    r = await client.post(
        f"/roadmaps/{rm['id']}/metrics",
        headers=_auth(tok),
        json={
            "name": "canonical",
            "baseline": "0 из 165",
            "baseline_on": "2026-10-28",
            "target": "165 из 165",
            "source": "краул site-crawl",
        },
    )
    assert r.status_code == 201, r.text
    metric = r.json()
    assert metric["position"] == 10

    r = await client.post(
        f"/roadmaps/{rm['id']}/metrics",
        headers=_auth(tok),
        json={"name": "H1", "baseline": "без H1 11 страниц", "target": "ровно один"},
    )
    assert r.json()["position"] == 20

    r = await client.patch(
        f"/roadmap-metrics/{metric['id']}",
        headers=_auth(tok),
        json={"current": "165 из 165", "measured_on": "2026-11-26", "reached_on": "2026-11-26"},
    )
    assert r.status_code == 200
    assert r.json()["current"] == "165 из 165"

    r = await client.get(f"/roadmaps/{rm['id']}", headers=_auth(tok))
    detail = r.json()
    assert detail["metric_count"] == 2
    assert detail["metric_reached_count"] == 1
    assert [m["name"] for m in detail["metrics"]] == ["canonical", "H1"]

    r = await client.delete(f"/roadmap-metrics/{metric['id']}", headers=_auth(tok))
    assert r.status_code == 204
    r = await client.get(f"/roadmaps/{rm['id']}/metrics", headers=_auth(tok))
    assert [m["name"] for m in r.json()] == ["H1"]


@pytest.mark.asyncio
async def test_visibility_and_manage_permission(client, session):
    ws, tok, proj = await _owner(client, session, code="RM5")
    rm = await _roadmap(client, tok, proj["id"])

    member_user = await make_user(session, ws, "member@ex.com", SystemRole.MEMBER)
    await session.commit()
    member = await _token(client, "member@ex.com")

    # нет доступа к проекту — роадмапа не существует (§7)
    r = await client.get(f"/roadmaps/{rm['id']}", headers=_auth(member))
    assert r.status_code == 404

    r = await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(tok),
        json={"user_id": str(member_user.id), "role": "MEMBER"},
    )
    assert r.status_code in (200, 201), r.text

    r = await client.get(f"/roadmaps/{rm['id']}", headers=_auth(member))
    assert r.status_code == 200
    # участник проекта роадмап видит, но не ведёт
    r = await client.patch(
        f"/roadmaps/{rm['id']}", headers=_auth(member), json={"title": "Моё"}
    )
    assert r.status_code == 403
    r = await client.post(
        f"/roadmaps/{rm['id']}/metrics", headers=_auth(member), json={"name": "x"}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_portfolio_timeline_and_archive(client, session):
    _, tok, proj = await _owner(client, session, code="RM6")
    rm = await _roadmap(client, tok, proj["id"])

    r = await client.post("/projects", headers=_auth(tok), json={"name": "Second", "code": "SEC"})
    second = r.json()
    await _roadmap(client, tok, second["id"], title="Месяц 1", period_start="2026-09-01")

    r = await client.get("/roadmap", headers=_auth(tok))
    assert r.status_code == 200
    rows = r.json()
    assert [row["project_code"] for row in rows] == ["SEC", "RM6"]

    r = await client.post(f"/roadmaps/{rm['id']}/archive", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["archived_at"] is not None

    r = await client.get("/roadmap", headers=_auth(tok))
    assert [row["project_code"] for row in r.json()] == ["SEC"]
    r = await client.get(f"/projects/{proj['id']}/roadmaps", headers=_auth(tok))
    assert r.json() == []
    r = await client.get(
        f"/projects/{proj['id']}/roadmaps?include_archived=true", headers=_auth(tok)
    )
    assert len(r.json()) == 1
