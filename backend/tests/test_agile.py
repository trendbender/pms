import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _project(client, tok, code="AG"):
    r = await client.post("/projects", headers=_auth(tok), json={"name": "P", "code": code})
    assert r.status_code == 201, r.text
    return r.json()


async def _task(client, tok, project_id, title="t", **extra):
    r = await client.post(
        "/tasks", headers=_auth(tok), json={"project_id": project_id, "title": title, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _statuses(client, tok, project_id):
    r = await client.get(f"/projects/{project_id}/statuses", headers=_auth(tok))
    return {s["category"]: s for s in r.json()}


async def _owner(client, session, code="AG"):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _project(client, tok, code=code)
    return tok, proj


# --------------------------------------------------------------------------- #
# Initiatives (§11)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_initiative_crud_and_task_progress(client, session):
    tok, proj = await _owner(client, session, code="INI")
    r = await client.post(
        f"/projects/{proj['id']}/initiatives",
        headers=_auth(tok),
        json={"name": "Increase Organic Bookings"},
    )
    assert r.status_code == 201
    ini = r.json()
    assert ini["task_count"] == 0

    # attach two tasks, complete one
    st = await _statuses(client, tok, proj["id"])
    t1 = await _task(client, tok, proj["id"], initiative_id=ini["id"])
    await _task(client, tok, proj["id"], initiative_id=ini["id"])
    await client.patch(
        f"/tasks/{t1['id']}/status", headers=_auth(tok), json={"status_id": st["DONE"]["id"]}
    )

    listed = await client.get(f"/projects/{proj['id']}/initiatives", headers=_auth(tok))
    row = listed.json()[0]
    assert row["task_count"] == 2
    assert row["done_count"] == 1

    # rename
    up = await client.patch(
        f"/initiatives/{ini['id']}", headers=_auth(tok), json={"name": "Organic Growth"}
    )
    assert up.json()["name"] == "Organic Growth"

    # delete -> tasks survive, initiative_id cleared
    d = await client.delete(f"/initiatives/{ini['id']}", headers=_auth(tok))
    assert d.status_code == 204
    t = await client.get(f"/tasks/{t1['id']}", headers=_auth(tok))
    assert t.json()["initiative_id"] is None


@pytest.mark.asyncio
async def test_member_cannot_manage_initiatives(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    dev = await make_user(session, ws, "dev@ex.com", SystemRole.MEMBER)
    await session.commit()
    otok = await _token(client, "owner@ex.com")
    proj = await _project(client, otok, code="IM")
    await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(otok),
        json={"user_id": str(dev.id), "role": "MEMBER"},
    )
    dtok = await _token(client, "dev@ex.com")
    r = await client.post(
        f"/projects/{proj['id']}/initiatives", headers=_auth(dtok), json={"name": "x"}
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Sprints (§26–§29)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sprint_start_requires_goal(client, session):
    tok, proj = await _owner(client, session, code="SP")
    r = await client.post(
        f"/projects/{proj['id']}/sprints", headers=_auth(tok), json={"name": "Sprint 1"}
    )
    assert r.status_code == 201
    sp = r.json()
    assert sp["status"] == "PLANNED"

    # no goal -> 422 (Rule 6)
    start = await client.post(f"/sprints/{sp['id']}/start", headers=_auth(tok))
    assert start.status_code == 422

    # set goal, then start succeeds with dates
    await client.patch(f"/sprints/{sp['id']}", headers=_auth(tok), json={"goal": "Ship SEO"})
    start2 = await client.post(f"/sprints/{sp['id']}/start", headers=_auth(tok))
    assert start2.status_code == 200
    assert start2.json()["status"] == "ACTIVE"
    assert start2.json()["start_date"] is not None
    assert start2.json()["end_date"] is not None


@pytest.mark.asyncio
async def test_only_one_active_sprint(client, session):
    tok, proj = await _owner(client, session, code="ONE")
    a = (
        await client.post(
            f"/projects/{proj['id']}/sprints",
            headers=_auth(tok),
            json={"name": "A", "goal": "g"},
        )
    ).json()
    b = (
        await client.post(
            f"/projects/{proj['id']}/sprints",
            headers=_auth(tok),
            json={"name": "B", "goal": "g"},
        )
    ).json()
    assert (await client.post(f"/sprints/{a['id']}/start", headers=_auth(tok))).status_code == 200
    conflict = await client.post(f"/sprints/{b['id']}/start", headers=_auth(tok))
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_sprint_stats_and_complete_to_backlog(client, session):
    tok, proj = await _owner(client, session, code="CMP")
    st = await _statuses(client, tok, proj["id"])
    sp = (
        await client.post(
            f"/projects/{proj['id']}/sprints",
            headers=_auth(tok),
            json={"name": "S1", "goal": "g"},
        )
    ).json()

    done_t = await _task(client, tok, proj["id"], sprint_id=sp["id"])
    open_t = await _task(client, tok, proj["id"], sprint_id=sp["id"])
    await client.patch(
        f"/tasks/{done_t['id']}/status", headers=_auth(tok), json={"status_id": st["DONE"]["id"]}
    )

    got = await client.get(f"/sprints/{sp['id']}", headers=_auth(tok))
    assert got.json()["stats"]["total"] == 2
    assert got.json()["stats"]["done"] == 1

    await client.post(f"/sprints/{sp['id']}/start", headers=_auth(tok))
    comp = await client.post(f"/sprints/{sp['id']}/complete", headers=_auth(tok), json={})
    assert comp.status_code == 200
    body = comp.json()
    assert body["completed"] == 1
    assert body["moved"] == 1
    assert body["moved_to"] == "backlog"
    assert body["sprint"]["status"] == "COMPLETED"

    # the incomplete task is back in the backlog (no sprint)
    t = await client.get(f"/tasks/{open_t['id']}", headers=_auth(tok))
    assert t.json()["sprint_id"] is None
    # the done task kept its sprint
    d = await client.get(f"/tasks/{done_t['id']}", headers=_auth(tok))
    assert d.json()["sprint_id"] == sp["id"]


@pytest.mark.asyncio
async def test_complete_carries_incomplete_to_next_sprint(client, session):
    tok, proj = await _owner(client, session, code="CAR")
    s1 = (
        await client.post(
            f"/projects/{proj['id']}/sprints",
            headers=_auth(tok),
            json={"name": "S1", "goal": "g"},
        )
    ).json()
    s2 = (
        await client.post(
            f"/projects/{proj['id']}/sprints",
            headers=_auth(tok),
            json={"name": "S2", "goal": "g"},
        )
    ).json()
    open_t = await _task(client, tok, proj["id"], sprint_id=s1["id"])
    await client.post(f"/sprints/{s1['id']}/start", headers=_auth(tok))

    comp = await client.post(
        f"/sprints/{s1['id']}/complete",
        headers=_auth(tok),
        json={"next_sprint_id": s2["id"]},
    )
    assert comp.status_code == 200
    assert comp.json()["moved_to"] == s2["id"]
    t = await client.get(f"/tasks/{open_t['id']}", headers=_auth(tok))
    assert t.json()["sprint_id"] == s2["id"]


# --------------------------------------------------------------------------- #
# Backlog (§12) + cross-project guards
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_backlog_excludes_sprinted_and_done_ordered_by_priority(client, session):
    tok, proj = await _owner(client, session, code="BL")
    st = await _statuses(client, tok, proj["id"])
    sp = (
        await client.post(
            f"/projects/{proj['id']}/sprints",
            headers=_auth(tok),
            json={"name": "S", "goal": "g"},
        )
    ).json()

    low = await _task(client, tok, proj["id"], title="low", priority="LOW")
    crit = await _task(client, tok, proj["id"], title="crit", priority="CRITICAL")
    await _task(client, tok, proj["id"], title="sprinted", sprint_id=sp["id"])
    done = await _task(client, tok, proj["id"], title="done")
    await client.patch(
        f"/tasks/{done['id']}/status", headers=_auth(tok), json={"status_id": st["DONE"]["id"]}
    )

    bl = await client.get(f"/projects/{proj['id']}/backlog", headers=_auth(tok))
    keys = [t["key"] for t in bl.json()]
    # only the two unsprinted, not-done tasks; CRITICAL before LOW
    assert keys == [crit["key"], low["key"]]


@pytest.mark.asyncio
async def test_task_sprint_from_other_project_rejected(client, session):
    tok, proj = await _owner(client, session, code="XA")
    other = await _project(client, tok, code="XB")
    other_sprint = (
        await client.post(
            f"/projects/{other['id']}/sprints",
            headers=_auth(tok),
            json={"name": "S", "goal": "g"},
        )
    ).json()
    r = await client.post(
        "/tasks",
        headers=_auth(tok),
        json={"project_id": proj["id"], "title": "t", "sprint_id": other_sprint["id"]},
    )
    assert r.status_code == 422
