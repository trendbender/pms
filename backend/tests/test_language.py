import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_me_defaults_to_ru(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "u@ex.com", SystemRole.MEMBER)
    await session.commit()
    tok = await _token(client, "u@ex.com")
    me = await client.get("/auth/me", headers=_auth(tok))
    assert me.status_code == 200
    assert me.json()["language"] == "ru"


@pytest.mark.asyncio
async def test_member_sets_own_language(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "u@ex.com", SystemRole.MEMBER)
    await session.commit()
    tok = await _token(client, "u@ex.com")

    r = await client.patch("/users/me", headers=_auth(tok), json={"language": "en"})
    assert r.status_code == 200, r.text
    assert r.json()["language"] == "en"

    # persisted — reflected on /auth/me
    me = await client.get("/auth/me", headers=_auth(tok))
    assert me.json()["language"] == "en"


@pytest.mark.asyncio
async def test_unsupported_language_rejected(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "u@ex.com", SystemRole.MEMBER)
    await session.commit()
    tok = await _token(client, "u@ex.com")
    r = await client.patch("/users/me", headers=_auth(tok), json={"language": "de"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_me_name(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "u@ex.com", SystemRole.MEMBER, name="Old")
    await session.commit()
    tok = await _token(client, "u@ex.com")
    r = await client.patch("/users/me", headers=_auth(tok), json={"name": "Новое имя"})
    assert r.status_code == 200
    assert r.json()["name"] == "Новое имя"
