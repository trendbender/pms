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


# --------------------------------------------------------------------------- #
# Creation / workflow seeding
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_owner_creates_project_seeds_workflow(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")

    proj = await _make_project(client, tok, code="seo")  # lower -> normalized
    assert proj["code"] == "SEO"
    assert proj["status"] == "DRAFT"
    assert proj["health"] == "ON_TRACK"

    statuses = await client.get(f"/projects/{proj['id']}/statuses", headers=_auth(tok))
    assert statuses.status_code == 200
    cats = [s["category"] for s in statuses.json()]
    assert cats == [
        "BACKLOG",
        "READY",
        "IN_PROGRESS",
        "BLOCKED",
        "REVIEW",
        "CHANGES_REQUIRED",
        "DONE",
    ]

    types = await client.get(f"/projects/{proj['id']}/types", headers=_auth(tok))
    assert {t["name"] for t in types.json()} == {
        "TASK",
        "BUG",
        "FEATURE",
        "IMPROVEMENT",
        "RESEARCH",
    }


@pytest.mark.asyncio
async def test_duplicate_code_conflicts(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    await _make_project(client, tok, code="UBO")
    r = await client.post("/projects", headers=_auth(tok), json={"name": "x", "code": "UBO"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_invalid_code_rejected(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    r = await client.post("/projects", headers=_auth(tok), json={"name": "x", "code": "1BAD!"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_member_cannot_create_project(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "m@ex.com", SystemRole.MEMBER)
    await session.commit()
    tok = await _token(client, "m@ex.com")
    r = await client.post("/projects", headers=_auth(tok), json={"name": "x", "code": "X"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_manager_can_create_and_owns_it(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "mgr@ex.com", SystemRole.MANAGER)
    await session.commit()
    tok = await _token(client, "mgr@ex.com")
    proj = await _make_project(client, tok, code="MGR")
    # manager is not a workspace superuser, but owns the project they created
    got = await client.get(f"/projects/{proj['id']}", headers=_auth(tok))
    assert got.status_code == 200


# --------------------------------------------------------------------------- #
# Visibility (spec §7)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_project_invisible_without_access(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await make_user(session, ws, "out@ex.com", SystemRole.MEMBER)
    await session.commit()

    owner_tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, owner_tok, code="SEC")

    out_tok = await _token(client, "out@ex.com")
    # 404 (not 403) so existence isn't leaked
    got = await client.get(f"/projects/{proj['id']}", headers=_auth(out_tok))
    assert got.status_code == 404

    listed = await client.get("/projects", headers=_auth(out_tok))
    assert listed.json() == []


@pytest.mark.asyncio
async def test_superuser_lists_all_projects(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await make_user(session, ws, "mgr@ex.com", SystemRole.MANAGER)
    await session.commit()

    mgr_tok = await _token(client, "mgr@ex.com")
    await _make_project(client, mgr_tok, code="AAA")

    owner_tok = await _token(client, "owner@ex.com")
    await _make_project(client, owner_tok, code="BBB")

    listed = await client.get("/projects", headers=_auth(owner_tok))
    assert {p["code"] for p in listed.json()} == {"AAA", "BBB"}


# --------------------------------------------------------------------------- #
# Update / archive
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_goal_and_health(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="GH")

    r = await client.patch(
        f"/projects/{proj['id']}",
        headers=_auth(tok),
        json={"goal": "Increase organic bookings 30%", "health": "AT_RISK"},
    )
    assert r.status_code == 200
    assert r.json()["goal"] == "Increase organic bookings 30%"
    assert r.json()["health"] == "AT_RISK"


@pytest.mark.asyncio
async def test_archive_project(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="ARC")
    r = await client.post(f"/projects/{proj['id']}/archive", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["status"] == "ARCHIVED"
    assert r.json()["archived_at"] is not None


# --------------------------------------------------------------------------- #
# Members + per-project roles
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_member_lifecycle_and_role_scoped_access(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    dev = await make_user(session, ws, "dev@ex.com", SystemRole.MEMBER)
    await session.commit()

    owner_tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, owner_tok, code="TEAM")

    # add dev as project MEMBER
    r = await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(owner_tok),
        json={"user_id": str(dev.id), "role": "MEMBER"},
    )
    assert r.status_code == 201

    members = await client.get(f"/projects/{proj['id']}/members", headers=_auth(owner_tok))
    emails = {m["email"] for m in members.json()}
    assert "dev@ex.com" in emails and "owner@ex.com" in emails

    dev_tok = await _token(client, "dev@ex.com")
    # dev can now see the project
    assert (await client.get(f"/projects/{proj['id']}", headers=_auth(dev_tok))).status_code == 200
    # but cannot edit it (MEMBER lacks project.edit)
    edit = await client.patch(
        f"/projects/{proj['id']}", headers=_auth(dev_tok), json={"goal": "x"}
    )
    assert edit.status_code == 403
    # and cannot manage members
    add = await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(dev_tok),
        json={"user_id": str(dev.id), "role": "MANAGER"},
    )
    assert add.status_code == 403

    # promote dev to MANAGER via re-post (upsert)
    up = await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(owner_tok),
        json={"user_id": str(dev.id), "role": "MANAGER"},
    )
    assert up.status_code == 201
    # now dev can edit
    edit2 = await client.patch(
        f"/projects/{proj['id']}", headers=_auth(dev_tok), json={"goal": "ok"}
    )
    assert edit2.status_code == 200

    # remove dev
    rm = await client.delete(
        f"/projects/{proj['id']}/members/{dev.id}", headers=_auth(owner_tok)
    )
    assert rm.status_code == 204
    assert (await client.get(f"/projects/{proj['id']}", headers=_auth(dev_tok))).status_code == 404


@pytest.mark.asyncio
async def test_cannot_add_user_from_other_workspace(client, session):
    ws = await make_workspace(session, "WS-A")
    ws_b = await make_workspace(session, "WS-B")
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    stranger = await make_user(session, ws_b, "stranger@ex.com", SystemRole.MEMBER)
    await session.commit()

    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="ISO")
    r = await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(tok),
        json={"user_id": str(stranger.id), "role": "MEMBER"},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Workflow config
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_status_config_crud(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="CFG")

    # create
    r = await client.post(
        f"/projects/{proj['id']}/statuses",
        headers=_auth(tok),
        json={"name": "QA", "category": "REVIEW"},
    )
    assert r.status_code == 201
    sid = r.json()["id"]

    # duplicate name conflicts
    dup = await client.post(
        f"/projects/{proj['id']}/statuses",
        headers=_auth(tok),
        json={"name": "QA", "category": "REVIEW"},
    )
    assert dup.status_code == 409

    # update
    upd = await client.patch(
        f"/projects/{proj['id']}/statuses/{sid}",
        headers=_auth(tok),
        json={"name": "QA Review"},
    )
    assert upd.status_code == 200 and upd.json()["name"] == "QA Review"

    # delete
    d = await client.delete(f"/projects/{proj['id']}/statuses/{sid}", headers=_auth(tok))
    assert d.status_code == 204
