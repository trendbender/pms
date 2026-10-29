"""Реестр решений: синк копии из вики, ссылки /d/, видимость, связь с задачами."""

from app.models.enums import ProjectRole, SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _item(ref, **kw):
    base = {"ref": ref, "status": "accepted", "question": f"Вопрос {ref}?", "area": "process"}
    base.update(kw)
    return base


async def _setup(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    r = await client.post("/projects", headers=_auth(tok), json={"name": "Skolko", "code": "SSK"})
    assert r.status_code == 201, r.text
    proj = r.json()
    r = await client.post(
        "/tasks", headers=_auth(tok), json={"project_id": proj["id"], "title": "Мастер"}
    )
    assert r.status_code == 201, r.text
    task = r.json()
    return ws, tok, proj, task


async def _sync(client, tok, registries):
    return await client.put("/decisions/sync", headers=_auth(tok), json={"registries": registries})


async def test_sync_and_read_by_ref(client, session):
    ws, tok, proj, task = await _setup(client, session)
    r = await _sync(client, tok, [
        {"registry": "skolkoskolko", "project_code": "SSK", "items": [
            _item("P-030", decision="Код на почту",
                  source=f"чат 21.10; https://pms/t/{task['key'].lower()}"),
            _item("P-031", status="open"),
        ]},
        {"registry": "_global", "project_code": None,
         "items": [_item("P-022", decision="Копия в PMS")]},
        {"registry": "nope", "project_code": "XXX", "items": [_item("S-001")]},
    ])
    assert r.status_code == 200, r.text
    out = {x["registry"]: x for x in r.json()["registries"]}
    assert out["skolkoskolko"]["created"] == 2
    assert out["_global"]["created"] == 1
    assert out["nope"]["skipped"] == "project not found"

    r = await client.get("/decisions/by-ref/SSK-P-030", headers=_auth(tok))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["full_ref"] == "SSK-P-030" and d["decision"] == "Код на почту"
    assert d["task_keys"] == [task["key"]]
    assert [t["key"] for t in d["tasks"]] == [task["key"]]

    # префикс по имени реестра и без ведущих нулей
    r = await client.get("/decisions/by-ref/skolkoskolko-p-30", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["ref"] == "P-030"
    r = await client.get("/decisions/by-ref/G-P-022", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["full_ref"] == "G-P-022"
    r = await client.get("/decisions/by-ref/SSK-P-999", headers=_auth(tok))
    assert r.status_code == 404

    r = await client.get(f"/projects/{proj['id']}/decisions?status=open", headers=_auth(tok))
    assert [x["ref"] for x in r.json()] == ["P-031"]
    r = await client.get(f"/projects/{proj['id']}/decisions?q=почту", headers=_auth(tok))
    assert [x["ref"] for x in r.json()] == ["P-030"]

    r = await client.get(f"/decisions/by-task/{task['key']}", headers=_auth(tok))
    assert [x["full_ref"] for x in r.json()] == ["SSK-P-030"]


async def test_resync_updates_and_deletes(client, session):
    ws, tok, proj, task = await _setup(client, session)
    reg = {"registry": "skolkoskolko", "project_code": "SSK",
           "items": [_item("P-001"), _item("P-002")]}
    assert (await _sync(client, tok, [reg])).status_code == 200
    reg["items"] = [_item("P-001", decision="новое", tasks=[task["key"]])]
    r = await _sync(client, tok, [reg])
    s = r.json()["registries"][0]
    assert (s["created"], s["updated"], s["deleted"]) == (0, 1, 1)
    r = await _sync(client, tok, [reg])
    s = r.json()["registries"][0]
    assert (s["created"], s["updated"], s["deleted"]) == (0, 0, 0)
    r = await client.get(f"/decisions/by-task/{task['key']}", headers=_auth(tok))
    assert [x["ref"] for x in r.json()] == ["P-001"]


async def test_bad_and_duplicate_refs_rejected(client, session):
    ws, tok, proj, task = await _setup(client, session)
    r = await _sync(client, tok, [{"registry": "skolkoskolko", "project_code": "SSK",
                                   "items": [_item("P-001"), _item("P-1")]}])
    assert r.status_code == 422
    r = await _sync(client, tok, [{"registry": "skolkoskolko", "project_code": "SSK",
                                   "items": [_item("PX-1")]}])
    assert r.status_code == 422


async def test_visibility(client, session):
    ws, tok, proj, task = await _setup(client, session)
    await _sync(client, tok, [
        {"registry": "skolkoskolko", "project_code": "SSK", "items": [_item("P-001")]},
        {"registry": "_global", "project_code": None, "items": [_item("P-001")]},
    ])
    member = await make_user(session, ws, "dev@ex.com", SystemRole.MEMBER)
    outsider = await make_user(session, ws, "out@ex.com", SystemRole.MEMBER)
    await session.commit()
    r = await client.post(f"/projects/{proj['id']}/members", headers=_auth(tok),
                          json={"user_id": str(member.id), "role": ProjectRole.MEMBER.value})
    assert r.status_code in (200, 201), r.text
    dev = await _token(client, "dev@ex.com")
    out = await _token(client, "out@ex.com")
    assert outsider is not None

    assert (await client.get("/decisions/by-ref/SSK-P-001", headers=_auth(dev))).status_code == 200
    assert (await client.get("/decisions/by-ref/SSK-P-001", headers=_auth(out))).status_code == 404
    # _global только владельцу и админам workspace
    assert (await client.get("/decisions/by-ref/G-P-001", headers=_auth(dev))).status_code == 404
    assert (await client.get("/decisions/global", headers=_auth(dev))).status_code == 404
    assert (await client.get("/decisions/global", headers=_auth(tok))).status_code == 200
    # синк только с правом workspace.manage
    r = await _sync(client, dev, [{"registry": "_global", "project_code": None, "items": []}])
    assert r.status_code == 403
