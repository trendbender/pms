import pytest

from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _make_project(client, tok, code="BD", wip=None):
    body = {"name": "Board project", "code": code}
    if wip is not None:
        body["wip_limit"] = wip
    r = await client.post("/projects", headers=_auth(tok), json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _make_task(client, tok, project_id, title="t"):
    r = await client.post(
        "/tasks", headers=_auth(tok), json={"project_id": project_id, "title": title}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _board(client, tok, project_id):
    r = await client.get(f"/projects/{project_id}/board", headers=_auth(tok))
    assert r.status_code == 200, r.text
    return r.json()


def _col(board, category):
    return next(c for c in board["columns"] if c["category"] == category)


# --------------------------------------------------------------------------- #
# Board shape (§23)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_board_columns_ordered_with_tasks(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="BRD")
    await _make_task(client, tok, proj["id"], "a")
    await _make_task(client, tok, proj["id"], "b")

    board = await _board(client, tok, proj["id"])
    cats = [c["category"] for c in board["columns"]]
    assert cats == [
        "BACKLOG",
        "READY",
        "IN_PROGRESS",
        "BLOCKED",
        "REVIEW",
        "CHANGES_REQUIRED",
        "DONE",
    ]
    # both new tasks land in BACKLOG
    assert len(_col(board, "BACKLOG")["tasks"]) == 2
    assert len(_col(board, "DONE")["tasks"]) == 0


# --------------------------------------------------------------------------- #
# Move between columns == status change (Rule 5)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_move_to_done_sets_completed_and_logs(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="MV")
    task = await _make_task(client, tok, proj["id"])
    board = await _board(client, tok, proj["id"])
    done = _col(board, "DONE")["status_id"]

    r = await client.patch(
        f"/tasks/{task['id']}/position",
        headers=_auth(tok),
        json={"status_id": done},
    )
    assert r.status_code == 200
    assert r.json()["status_category"] == "DONE"
    assert r.json()["completed_at"] is not None

    feed = await client.get(f"/tasks/{task['id']}/activity", headers=_auth(tok))
    assert "status.changed" in [a["action"] for a in feed.json()]


# --------------------------------------------------------------------------- #
# Reorder within a column (fractional positions, §56)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reorder_within_column(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="RO")
    t1 = await _make_task(client, tok, proj["id"], "one")
    t2 = await _make_task(client, tok, proj["id"], "two")
    t3 = await _make_task(client, tok, proj["id"], "three")
    board = await _board(client, tok, proj["id"])
    backlog = _col(board, "BACKLOG")
    sid = backlog["status_id"]
    # initial order t1, t2, t3
    assert [t["key"] for t in backlog["tasks"]] == [t1["key"], t2["key"], t3["key"]]

    # move t3 between t1 and t2
    r = await client.patch(
        f"/tasks/{t3['id']}/position",
        headers=_auth(tok),
        json={"status_id": sid, "after_id": t1["id"], "before_id": t2["id"]},
    )
    assert r.status_code == 200

    board2 = await _board(client, tok, proj["id"])
    order = [t["key"] for t in _col(board2, "BACKLOG")["tasks"]]
    assert order == [t1["key"], t3["key"], t2["key"]]

    feed = await client.get(f"/tasks/{t3['id']}/activity", headers=_auth(tok))
    assert "task.moved" in [a["action"] for a in feed.json()]


# --------------------------------------------------------------------------- #
# WIP limit is a soft warning, never a block (§25)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_wip_limit_warns_but_does_not_block(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, tok, code="WIP", wip=1)
    board = await _board(client, tok, proj["id"])
    inprog = _col(board, "IN_PROGRESS")["status_id"]

    t1 = await _make_task(client, tok, proj["id"], "a")
    t2 = await _make_task(client, tok, proj["id"], "b")
    # move both into IN_PROGRESS (limit 1) — neither is blocked
    for t in (t1, t2):
        r = await client.patch(
            f"/tasks/{t['id']}/position", headers=_auth(tok), json={"status_id": inprog}
        )
        assert r.status_code == 200

    board2 = await _board(client, tok, proj["id"])
    col = _col(board2, "IN_PROGRESS")
    assert col["wip_limit"] == 1
    assert len(col["tasks"]) == 2
    assert col["wip_exceeded"] is True


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_move_neighbour_must_be_same_project(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    a = await _make_project(client, tok, code="PA")
    b = await _make_project(client, tok, code="PB")
    ta = await _make_task(client, tok, a["id"])
    tb = await _make_task(client, tok, b["id"])
    board_a = await _board(client, tok, a["id"])
    sid = _col(board_a, "BACKLOG")["status_id"]

    r = await client.patch(
        f"/tasks/{ta['id']}/position",
        headers=_auth(tok),
        json={"status_id": sid, "after_id": tb["id"]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_viewer_cannot_move(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    viewer = await make_user(session, ws, "v@ex.com", SystemRole.MEMBER)
    await session.commit()
    owner_tok = await _token(client, "owner@ex.com")
    proj = await _make_project(client, owner_tok, code="VW")
    await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(owner_tok),
        json={"user_id": str(viewer.id), "role": "VIEWER"},
    )
    task = await _make_task(client, owner_tok, proj["id"])
    board = await _board(client, owner_tok, proj["id"])
    done = _col(board, "DONE")["status_id"]

    v_tok = await _token(client, "v@ex.com")
    r = await client.patch(
        f"/tasks/{task['id']}/position", headers=_auth(v_tok), json={"status_id": done}
    )
    assert r.status_code == 403
