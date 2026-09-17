import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _project(client, tok, code="SR"):
    r = await client.post("/projects", headers=_auth(tok), json={"name": "P", "code": code})
    return r.json()


async def _task(client, tok, project_id, **extra):
    r = await client.post(
        "/tasks", headers=_auth(tok), json={"project_id": project_id, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_search_by_title_and_key(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _project(client, tok, code="SEO")
    hit = await _task(client, tok, proj["id"], title="Fix canonical tags")
    await _task(client, tok, proj["id"], title="Unrelated work")

    r = await client.get("/search?q=canonical", headers=_auth(tok))
    assert r.status_code == 200
    assert [t["key"] for t in r.json()] == [hit["key"]]

    # by key
    bykey = await client.get(f"/search?q={hit['key']}", headers=_auth(tok))
    assert hit["key"] in [t["key"] for t in bykey.json()]


@pytest.mark.asyncio
async def test_search_matches_comment_body(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _project(client, tok, code="CM")
    task = await _task(client, tok, proj["id"], title="Some task")
    await client.post(
        f"/tasks/{task['id']}/comments",
        headers=_auth(tok),
        json={"body": "blocked by hreflang issue"},
    )
    r = await client.get("/search?q=hreflang", headers=_auth(tok))
    assert [t["key"] for t in r.json()] == [task["key"]]


@pytest.mark.asyncio
async def test_search_scoped_to_visible_projects(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await make_user(session, ws, "out@ex.com", SystemRole.MEMBER)
    await session.commit()
    otok = await _token(client, "owner@ex.com")
    proj = await _project(client, otok, code="HID")
    await _task(client, otok, proj["id"], title="secret canonical thing")

    out = await _token(client, "out@ex.com")
    r = await client.get("/search?q=canonical", headers=_auth(out))
    assert r.json() == []
