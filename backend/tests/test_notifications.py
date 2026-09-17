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
    owner = await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    dev = await make_user(session, ws, "dev@ex.com", SystemRole.MEMBER)
    await session.commit()
    otok = await _token(client, "owner@ex.com")
    proj = (
        await client.post("/projects", headers=_auth(otok), json={"name": "P", "code": "P"})
    ).json()
    await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(otok),
        json={"user_id": str(dev.id), "role": "MEMBER"},
    )
    dtok = await _token(client, "dev@ex.com")
    st = {
        s["category"]: s
        for s in (
            await client.get(f"/projects/{proj['id']}/statuses", headers=_auth(otok))
        ).json()
    }
    return owner, dev, otok, dtok, proj, st


async def _count(client, tok):
    r = await client.get("/me/notifications/count", headers=_auth(tok))
    return r.json()["unread"]


@pytest.mark.asyncio
async def test_assign_notifies_assignee_not_actor(client, session):
    owner, dev, otok, dtok, proj, st = await _setup(client, session)
    # owner assigns a task to dev
    await client.post(
        "/tasks",
        headers=_auth(otok),
        json={"project_id": proj["id"], "title": "do it", "assignee_id": str(dev.id)},
    )
    assert await _count(client, dtok) == 1
    # the actor (owner) is not notified about their own action
    assert await _count(client, otok) == 0

    notes = await client.get("/me/notifications", headers=_auth(dtok))
    assert notes.json()[0]["kind"] == "task.assigned"


@pytest.mark.asyncio
async def test_self_assign_no_notification(client, session):
    owner, dev, otok, dtok, proj, st = await _setup(client, session)
    await client.post(
        "/tasks",
        headers=_auth(otok),
        json={"project_id": proj["id"], "title": "mine", "assignee_id": str(owner.id)},
    )
    assert await _count(client, otok) == 0


@pytest.mark.asyncio
async def test_review_and_changes_requested(client, session):
    owner, dev, otok, dtok, proj, st = await _setup(client, session)
    # dev's task, owner is reviewer
    task = (
        await client.post(
            "/tasks",
            headers=_auth(otok),
            json={
                "project_id": proj["id"],
                "title": "t",
                "assignee_id": str(dev.id),
                "reviewer_id": str(owner.id),
            },
        )
    ).json()
    # dev moves it to REVIEW -> owner (reviewer) notified
    await client.patch(
        f"/tasks/{task['id']}/status", headers=_auth(dtok), json={"status_id": st["REVIEW"]["id"]}
    )
    owner_notes = await client.get("/me/notifications?unread=true", headers=_auth(otok))
    assert any(n["kind"] == "review.requested" for n in owner_notes.json())

    # owner requests changes -> dev (assignee) notified
    before = await _count(client, dtok)
    await client.patch(
        f"/tasks/{task['id']}/status",
        headers=_auth(otok),
        json={"status_id": st["CHANGES_REQUIRED"]["id"]},
    )
    dev_notes = await client.get("/me/notifications", headers=_auth(dtok))
    assert any(n["kind"] == "changes.requested" for n in dev_notes.json())
    assert await _count(client, dtok) == before + 1


@pytest.mark.asyncio
async def test_comment_notifies_participants(client, session):
    owner, dev, otok, dtok, proj, st = await _setup(client, session)
    task = (
        await client.post(
            "/tasks",
            headers=_auth(otok),
            json={"project_id": proj["id"], "title": "t", "assignee_id": str(dev.id)},
        )
    ).json()
    dev_before = await _count(client, dtok)
    # owner comments -> dev (assignee) notified, owner (author) not
    await client.post(
        f"/tasks/{task['id']}/comments", headers=_auth(otok), json={"body": "hello"}
    )
    assert await _count(client, dtok) == dev_before + 1


@pytest.mark.asyncio
async def test_mark_read_and_read_all(client, session):
    owner, dev, otok, dtok, proj, st = await _setup(client, session)
    await client.post(
        "/tasks",
        headers=_auth(otok),
        json={"project_id": proj["id"], "title": "a", "assignee_id": str(dev.id)},
    )
    await client.post(
        "/tasks",
        headers=_auth(otok),
        json={"project_id": proj["id"], "title": "b", "assignee_id": str(dev.id)},
    )
    assert await _count(client, dtok) == 2
    notes = (await client.get("/me/notifications", headers=_auth(dtok))).json()
    r = await client.post(f"/notifications/{notes[0]['id']}/read", headers=_auth(dtok))
    assert r.status_code == 200
    assert await _count(client, dtok) == 1

    allr = await client.post("/me/notifications/read-all", headers=_auth(dtok))
    assert allr.json()["unread"] == 0
    assert await _count(client, dtok) == 0


@pytest.mark.asyncio
async def test_cannot_read_others_notification(client, session):
    owner, dev, otok, dtok, proj, st = await _setup(client, session)
    await client.post(
        "/tasks",
        headers=_auth(otok),
        json={"project_id": proj["id"], "title": "a", "assignee_id": str(dev.id)},
    )
    notes = (await client.get("/me/notifications", headers=_auth(dtok))).json()
    # owner tries to mark dev's notification read -> 404
    r = await client.post(f"/notifications/{notes[0]['id']}/read", headers=_auth(otok))
    assert r.status_code == 404
