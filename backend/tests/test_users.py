import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_owner_can_invite_user(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER, "secret12345")
    await session.commit()

    tok = await _token(client, "owner@ex.com", "secret12345")
    r = await client.post(
        "/users/invite",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "email": "dev@ex.com",
            "name": "Dev",
            "system_role": "MEMBER",
            "initial_password": "devpass12345",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "dev@ex.com"

    # the invited user can now authenticate
    dev_tok = await _token(client, "dev@ex.com", "devpass12345")
    assert dev_tok


@pytest.mark.asyncio
async def test_member_cannot_invite(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER, "secret12345")
    await make_user(session, ws, "member@ex.com", SystemRole.MEMBER, "secret12345")
    await session.commit()

    tok = await _token(client, "member@ex.com", "secret12345")
    r = await client.post(
        "/users/invite",
        headers={"Authorization": f"Bearer {tok}"},
        json={"email": "x@ex.com", "name": "X"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_invite_duplicate_email_conflicts(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER, "secret12345")
    await session.commit()

    tok = await _token(client, "owner@ex.com", "secret12345")
    payload = {"email": "dup@ex.com", "name": "Dup", "initial_password": "pass12345678"}
    first = await client.post(
        "/users/invite", headers={"Authorization": f"Bearer {tok}"}, json=payload
    )
    assert first.status_code == 201
    second = await client.post(
        "/users/invite", headers={"Authorization": f"Bearer {tok}"}, json=payload
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_owner_can_change_role_and_suspend(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER, "secret12345")
    member = await make_user(session, ws, "m@ex.com", SystemRole.MEMBER, "secret12345")
    await session.commit()

    tok = await _token(client, "owner@ex.com", "secret12345")

    # promote to MANAGER
    r = await client.patch(
        f"/users/{member.id}",
        headers={"Authorization": f"Bearer {tok}"},
        json={"system_role": "MANAGER"},
    )
    assert r.status_code == 200
    assert r.json()["system_role"] == "MANAGER"

    # suspend -> the member can no longer authenticate against protected routes
    r = await client.patch(
        f"/users/{member.id}",
        headers={"Authorization": f"Bearer {tok}"},
        json={"is_suspended": True},
    )
    assert r.status_code == 200
    assert r.json()["is_suspended"] is True

    login = await client.post(
        "/auth/login", json={"email": "m@ex.com", "password": "secret12345"}
    )
    assert login.status_code == 403


@pytest.mark.asyncio
async def test_list_users_scoped_to_workspace(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER, "secret12345")
    await make_user(session, ws, "a@ex.com", SystemRole.MEMBER, "secret12345")
    await session.commit()

    tok = await _token(client, "owner@ex.com", "secret12345")
    r = await client.get("/users", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()}
    assert emails == {"owner@ex.com", "a@ex.com"}
