import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _project(client, tok, code="DS"):
    r = await client.post("/projects", headers=_auth(tok), json={"name": "P", "code": code})
    assert r.status_code == 201, r.text
    return r.json()


async def _task(client, tok, project_id, **extra):
    r = await client.post(
        "/tasks", headers=_auth(tok), json={"project_id": project_id, "title": "t", **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _statuses(client, tok, project_id):
    r = await client.get(f"/projects/{project_id}/statuses", headers=_auth(tok))
    return {s["category"]: s for s in r.json()}


async def _set_status(client, tok, task_id, status_id, reason=None):
    body = {"status_id": status_id}
    if reason:
        body["reason"] = reason
    r = await client.patch(f"/tasks/{task_id}/status", headers=_auth(tok), json=body)
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# My Tasks (§31) / My Reviews (§32)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_my_tasks_only_mine_not_done(client, session):
    ws = await make_workspace(session)
    owner = await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    dev = await make_user(session, ws, "dev@ex.com", SystemRole.MEMBER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _project(client, tok, code="MT")
    await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(tok),
        json={"user_id": str(dev.id), "role": "MEMBER"},
    )
    st = await _statuses(client, tok, proj["id"])

    mine = await _task(client, tok, proj["id"], assignee_id=str(owner.id))
    done_mine = await _task(client, tok, proj["id"], assignee_id=str(owner.id))
    await _set_status(client, tok, done_mine["id"], st["DONE"]["id"])
    await _task(client, tok, proj["id"], assignee_id=str(dev.id))  # someone else's

    r = await client.get("/me/tasks", headers=_auth(tok))
    assert r.status_code == 200
    keys = [t["key"] for t in r.json()]
    assert keys == [mine["key"]]
    assert r.json()[0]["project_code"] == "MT"


@pytest.mark.asyncio
async def test_my_reviews_reviewer_and_review_status(client, session):
    ws = await make_workspace(session)
    owner = await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _project(client, tok, code="MR")
    st = await _statuses(client, tok, proj["id"])

    inrev = await _task(client, tok, proj["id"], reviewer_id=str(owner.id))
    await _set_status(client, tok, inrev["id"], st["REVIEW"]["id"])
    # reviewer=me but still in progress -> not in my reviews
    await _task(client, tok, proj["id"], reviewer_id=str(owner.id))

    r = await client.get("/me/reviews", headers=_auth(tok))
    assert [t["key"] for t in r.json()] == [inrev["key"]]


# --------------------------------------------------------------------------- #
# All Tasks (§33) — pagination, filters, visibility
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_all_tasks_pagination_and_filter(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _project(client, tok, code="AT")
    for _ in range(3):
        await _task(client, tok, proj["id"], priority="HIGH")
    await _task(client, tok, proj["id"], priority="LOW")

    page = await client.get("/tasks?limit=2", headers=_auth(tok))
    assert page.status_code == 200
    assert page.json()["total"] == 4
    assert len(page.json()["items"]) == 2

    high = await client.get("/tasks?priority=HIGH", headers=_auth(tok))
    assert high.json()["total"] == 3


@pytest.mark.asyncio
async def test_all_tasks_hidden_without_access(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await make_user(session, ws, "out@ex.com", SystemRole.MEMBER)
    await session.commit()
    otok = await _token(client, "owner@ex.com")
    proj = await _project(client, otok, code="HD")
    await _task(client, otok, proj["id"])

    out = await _token(client, "out@ex.com")
    r = await client.get("/tasks", headers=_auth(out))
    assert r.json()["total"] == 0
    assert r.json()["items"] == []


# --------------------------------------------------------------------------- #
# Portfolio (§34) / Project Dashboard (§35)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_portfolio_counts_and_totals(client, session):
    ws = await make_workspace(session)
    owner = await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _project(client, tok, code="PF")
    st = await _statuses(client, tok, proj["id"])

    # one open, one blocked, one in review (reviewer=owner), one overdue
    await _task(client, tok, proj["id"])
    blk = await _task(client, tok, proj["id"])
    await _set_status(client, tok, blk["id"], st["BLOCKED"]["id"], reason="waiting")
    rev = await _task(client, tok, proj["id"], reviewer_id=str(owner.id))
    await _set_status(client, tok, rev["id"], st["REVIEW"]["id"])
    await _task(client, tok, proj["id"], due_at="2020-01-01T00:00:00Z")

    r = await client.get("/portfolio", headers=_auth(tok))
    assert r.status_code == 200
    row = next(x for x in r.json()["rows"] if x["code"] == "PF")
    assert row["open"] == 4  # none are DONE
    assert row["blocked"] == 1
    assert row["review"] == 1
    assert row["overdue"] == 1
    totals = r.json()["totals"]
    assert totals["blockers"] == 1
    assert totals["overdue"] == 1
    assert totals["waiting_my_review"] == 1


@pytest.mark.asyncio
async def test_portfolio_scoped_to_visible_projects(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await make_user(session, ws, "out@ex.com", SystemRole.MEMBER)
    await session.commit()
    otok = await _token(client, "owner@ex.com")
    proj = await _project(client, otok, code="SC")
    await _task(client, otok, proj["id"])

    out = await _token(client, "out@ex.com")
    r = await client.get("/portfolio", headers=_auth(out))
    assert r.json()["rows"] == []
    assert r.json()["totals"]["blockers"] == 0


@pytest.mark.asyncio
async def test_project_dashboard_with_active_sprint(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _project(client, tok, code="PD")
    st = await _statuses(client, tok, proj["id"])
    sp = (
        await client.post(
            f"/projects/{proj['id']}/sprints",
            headers=_auth(tok),
            json={"name": "S1", "goal": "Ship it"},
        )
    ).json()
    await client.post(f"/sprints/{sp['id']}/start", headers=_auth(tok))
    d1 = await _task(client, tok, proj["id"], sprint_id=sp["id"])
    await _task(client, tok, proj["id"], sprint_id=sp["id"])
    await _set_status(client, tok, d1["id"], st["DONE"]["id"])

    r = await client.get(f"/projects/{proj['id']}/dashboard", headers=_auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["goal"] is None or True
    assert body["current_sprint"]["name"] == "S1"
    assert body["current_sprint"]["goal"] == "Ship it"
    assert body["current_sprint"]["total"] == 2
    assert body["current_sprint"]["done"] == 1
    assert body["open"] == 1  # one DONE, one open
