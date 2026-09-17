import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _make_project(client, tok, code="SEO", name="SEO project"):
    r = await client.post(
        "/projects", headers=_auth(tok), json={"name": name, "code": code, "goal": "Grow"}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _statuses(client, tok, project_id):
    r = await client.get(f"/projects/{project_id}/statuses", headers=_auth(tok))
    assert r.status_code == 200
    return {s["category"]: s for s in r.json()}


async def _make_task(client, tok, project_id, **body):
    payload = {"project_id": project_id, "title": "Fix canonical", **body}
    r = await client.post("/tasks", headers=_auth(tok), json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Creation, key/number allocation, defaults (§13, §14, §18)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_task_minimal_gets_key_and_defaults(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="SEO")

    task = await _make_task(client, tok, proj["id"])
    assert task["key"] == "SEO-1"
    assert task["number"] == 1
    assert task["status_category"] == "BACKLOG"
    assert task["priority"] == "MEDIUM"
    assert task["type_name"] == "TASK"
    assert task["reporter_id"] is not None


@pytest.mark.asyncio
async def test_task_numbers_increment_per_project(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    a = await _make_project(client, tok, code="AAA")
    b = await _make_project(client, tok, code="BBB")

    assert (await _make_task(client, tok, a["id"]))["key"] == "AAA-1"
    assert (await _make_task(client, tok, a["id"]))["key"] == "AAA-2"
    # separate counter per project
    assert (await _make_task(client, tok, b["id"]))["key"] == "BBB-1"


# --------------------------------------------------------------------------- #
# Permissions & visibility (§7, §8)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_member_can_create_viewer_cannot(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    dev = await make_user(session, ws, "dev@ex.com", SystemRole.MEMBER)
    viewer = await make_user(session, ws, "view@ex.com", SystemRole.MEMBER)
    await session.commit()

    owner_tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, owner_tok, code="TEAM")
    await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(owner_tok),
        json={"user_id": str(dev.id), "role": "MEMBER"},
    )
    await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(owner_tok),
        json={"user_id": str(viewer.id), "role": "VIEWER"},
    )

    dev_tok = await _token(client, "dev@ex.com")
    r = await client.post(
        "/tasks", headers=_auth(dev_tok), json={"project_id": proj["id"], "title": "t"}
    )
    assert r.status_code == 201

    viewer_tok = await _token(client, "view@ex.com")
    r2 = await client.post(
        "/tasks", headers=_auth(viewer_tok), json={"project_id": proj["id"], "title": "t"}
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_task_invisible_without_project_access(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await make_user(session, ws, "out@ex.com", SystemRole.MEMBER)
    await session.commit()
    owner_tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, owner_tok, code="SEC")
    task = await _make_task(client, owner_tok, proj["id"])

    out_tok = await _token(client, "out@ex.com")
    got = await client.get(f"/tasks/{task['id']}", headers=_auth(out_tok))
    assert got.status_code == 404  # not 403 — existence not leaked


# --------------------------------------------------------------------------- #
# Status transitions: review / done / blocked (Rules 4, 5, 8)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_status_done_sets_completed_and_reopen_clears(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="ST")
    task = await _make_task(client, tok, proj["id"])
    st = await _statuses(client, tok, proj["id"])

    done = await client.patch(
        f"/tasks/{task['id']}/status", headers=_auth(tok), json={"status_id": st["DONE"]["id"]}
    )
    assert done.status_code == 200
    assert done.json()["completed_at"] is not None
    assert done.json()["status_category"] == "DONE"

    # reopen -> completed_at cleared
    reopen = await client.patch(
        f"/tasks/{task['id']}/status",
        headers=_auth(tok),
        json={"status_id": st["IN_PROGRESS"]["id"]},
    )
    assert reopen.json()["completed_at"] is None


@pytest.mark.asyncio
async def test_blocked_sets_flag_and_reason(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="BL")
    task = await _make_task(client, tok, proj["id"])
    st = await _statuses(client, tok, proj["id"])

    r = await client.patch(
        f"/tasks/{task['id']}/status",
        headers=_auth(tok),
        json={"status_id": st["BLOCKED"]["id"], "reason": "waiting on client access"},
    )
    assert r.json()["is_blocked"] is True
    assert r.json()["blocked_reason"] == "waiting on client access"

    # moving out of blocked clears it
    r2 = await client.patch(
        f"/tasks/{task['id']}/status",
        headers=_auth(tok),
        json={"status_id": st["READY"]["id"]},
    )
    assert r2.json()["is_blocked"] is False
    assert r2.json()["blocked_reason"] is None


@pytest.mark.asyncio
async def test_status_from_other_project_rejected(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    a = await _make_project(client, tok, code="AA")
    b = await _make_project(client, tok, code="BB")
    task = await _make_task(client, tok, a["id"])
    b_statuses = await _statuses(client, tok, b["id"])

    r = await client.patch(
        f"/tasks/{task['id']}/status",
        headers=_auth(tok),
        json={"status_id": b_statuses["DONE"]["id"]},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Assignee / reviewer must have project access (§7, §22)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_assignee_must_have_project_access(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    dev = await make_user(session, ws, "dev@ex.com", SystemRole.MEMBER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="AS")

    # dev is not a project member yet -> 422
    r = await client.post(
        "/tasks",
        headers=_auth(tok),
        json={"project_id": proj["id"], "title": "t", "assignee_id": str(dev.id)},
    )
    assert r.status_code == 422

    # add dev, then assignment works
    await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(tok),
        json={"user_id": str(dev.id), "role": "MEMBER"},
    )
    r2 = await client.post(
        "/tasks",
        headers=_auth(tok),
        json={"project_id": proj["id"], "title": "t", "assignee_id": str(dev.id)},
    )
    assert r2.status_code == 201
    assert r2.json()["assignee_id"] == str(dev.id)


# --------------------------------------------------------------------------- #
# Update, activity log, delete, list filters
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_logs_activity(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="AC")
    task = await _make_task(client, tok, proj["id"])

    upd = await client.patch(
        f"/tasks/{task['id']}",
        headers=_auth(tok),
        json={"priority": "CRITICAL", "acceptance_criteria": "no canonical errors left"},
    )
    assert upd.status_code == 200
    assert upd.json()["priority"] == "CRITICAL"

    feed = await client.get(f"/tasks/{task['id']}/activity", headers=_auth(tok))
    actions = [a["action"] for a in feed.json()]
    assert "task.created" in actions
    assert "priority.changed" in actions


@pytest.mark.asyncio
async def test_delete_task_soft(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="DEL")
    task = await _make_task(client, tok, proj["id"])

    d = await client.delete(f"/tasks/{task['id']}", headers=_auth(tok))
    assert d.status_code == 204
    assert (await client.get(f"/tasks/{task['id']}", headers=_auth(tok))).status_code == 404
    listed = await client.get(f"/projects/{proj['id']}/tasks", headers=_auth(tok))
    assert task["id"] not in [t["id"] for t in listed.json()]


@pytest.mark.asyncio
async def test_list_filters_by_category(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="LF")
    st = await _statuses(client, tok, proj["id"])
    t1 = await _make_task(client, tok, proj["id"], title="one")
    await _make_task(client, tok, proj["id"], title="two")
    await client.patch(
        f"/tasks/{t1['id']}/status", headers=_auth(tok), json={"status_id": st["DONE"]["id"]}
    )

    done = await client.get(
        f"/projects/{proj['id']}/tasks?category=DONE", headers=_auth(tok)
    )
    assert [t["id"] for t in done.json()] == [t1["id"]]
    backlog = await client.get(
        f"/projects/{proj['id']}/tasks?category=BACKLOG", headers=_auth(tok)
    )
    assert len(backlog.json()) == 1
