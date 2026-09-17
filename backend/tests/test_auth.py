import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["api"] is True
    assert body["checks"]["postgres"] is True


@pytest.mark.asyncio
async def test_login_success_and_me(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER, "secret12345")
    await session.commit()

    r = await client.post(
        "/auth/login", json={"email": "owner@ex.com", "password": "secret12345"}
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    me = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "owner@ex.com"
    assert me.json()["system_role"] == "OWNER"


@pytest.mark.asyncio
async def test_login_wrong_password(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "u@ex.com", SystemRole.MEMBER, "correcthorse")
    await session.commit()

    r = await client.post("/auth/login", json={"email": "u@ex.com", "password": "nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client):
    r = await client.post("/auth/login", json={"email": "ghost@ex.com", "password": "whatever"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "r@ex.com", SystemRole.MEMBER, "secret12345")
    await session.commit()

    login = await client.post(
        "/auth/login", json={"email": "r@ex.com", "password": "secret12345"}
    )
    refresh_token = login.json()["refresh_token"]

    r = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    assert r.json()["access_token"]

    # an access token must not be usable as a refresh token
    access = login.json()["access_token"]
    bad = await client.post("/auth/refresh", json={"refresh_token": access})
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401
