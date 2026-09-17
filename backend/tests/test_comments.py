import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _setup(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    dev = await make_user(session, ws, "dev@ex.com", SystemRole.MEMBER)
    await session.commit()
    owner_tok = await _token(client, "owner@ex.com")
    proj = await client.post(
        "/projects", headers=_auth(owner_tok), json={"name": "P", "code": "P"}
    )
    proj = proj.json()
    await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(owner_tok),
        json={"user_id": str(dev.id), "role": "MEMBER"},
    )
    task = await client.post(
        "/tasks", headers=_auth(owner_tok), json={"project_id": proj["id"], "title": "t"}
    )
    return owner_tok, await _token(client, "dev@ex.com"), proj, task.json()


@pytest.mark.asyncio
async def test_create_and_list_comments(client, session):
    owner_tok, dev_tok, proj, task = await _setup(client, session)
    r = await client.post(
        f"/tasks/{task['id']}/comments", headers=_auth(dev_tok), json={"body": "@owner check /x"}
    )
    assert r.status_code == 201
    assert r.json()["body"] == "@owner check /x"

    listed = await client.get(f"/tasks/{task['id']}/comments", headers=_auth(owner_tok))
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_author_edits_own_others_cannot(client, session):
    owner_tok, dev_tok, proj, task = await _setup(client, session)
    c = await client.post(
        f"/tasks/{task['id']}/comments", headers=_auth(dev_tok), json={"body": "first"}
    )
    cid = c.json()["id"]

    # author edits own -> ok, edited_at set
    up = await client.patch(
        f"/comments/{cid}", headers=_auth(dev_tok), json={"body": "edited"}
    )
    assert up.status_code == 200
    assert up.json()["body"] == "edited"
    assert up.json()["edited_at"] is not None

    # owner (not author) cannot edit someone else's comment
    up2 = await client.patch(
        f"/comments/{cid}", headers=_auth(owner_tok), json={"body": "nope"}
    )
    assert up2.status_code == 403


@pytest.mark.asyncio
async def test_manager_can_delete_any_author_can_delete_own(client, session):
    owner_tok, dev_tok, proj, task = await _setup(client, session)
    c = await client.post(
        f"/tasks/{task['id']}/comments", headers=_auth(dev_tok), json={"body": "x"}
    )
    cid = c.json()["id"]
    # owner (workspace superuser -> COMMENT_DELETE) can delete another's comment
    d = await client.delete(f"/comments/{cid}", headers=_auth(owner_tok))
    assert d.status_code == 204
    # gone from listing
    listed = await client.get(f"/tasks/{task['id']}/comments", headers=_auth(owner_tok))
    assert listed.json() == []


@pytest.mark.asyncio
async def test_comment_hidden_without_project_access(client, session):
    owner_tok, dev_tok, proj, task = await _setup(client, session)
    await client.post(
        f"/tasks/{task['id']}/comments", headers=_auth(owner_tok), json={"body": "secret"}
    )
    # an outsider with no project access
    await make_user(session, (await _ws_of(session)), "out@ex.com", SystemRole.MEMBER)
    await session.commit()
    out_tok = await _token(client, "out@ex.com")
    got = await client.get(f"/tasks/{task['id']}/comments", headers=_auth(out_tok))
    assert got.status_code == 404


async def _ws_of(session):
    from sqlalchemy import select

    from app.models.workspace import Workspace

    return await session.scalar(select(Workspace).limit(1))
