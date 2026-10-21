"""Номера ключей (KL-L-N, KL-N) под параллельными созданиями.

Счётчик на проекте раньше увеличивался в Python (read-modify-write): два параллельных
запроса читали одно значение, второй падал на уникальном ключе. На лидах это было 409
«source and external_id exists», на задачах 500, а в ingest без external_id второй
лид молча подменялся чужим существующим (created=False). asyncio.gather поверх
ASGITransport даёт настоящую параллельность на уровне БД: у каждого запроса своя
сессия и своё соединение (NullPool в conftest).
"""

import asyncio

import pytest

from tests.test_leads import _auth, _owner_project

N = 12


def _numbers(keys, prefix):
    return sorted(int(k.removeprefix(prefix)) for k in keys)


@pytest.mark.asyncio
async def test_parallel_lead_creates_get_unique_keys(client, session):
    _, tok, proj, _ = await _owner_project(client, session)
    pid, h = proj["id"], _auth(tok)

    rs = await asyncio.gather(*[
        client.post(f"/projects/{pid}/leads", headers=h, json={"title": f"лид {i}"})
        for i in range(N)
    ])
    assert [r.status_code for r in rs] == [201] * N, [r.text for r in rs if r.status_code != 201]
    assert _numbers([r.json()["key"] for r in rs], "KL-L-") == list(range(1, N + 1))


@pytest.mark.asyncio
async def test_parallel_ingest_without_external_id_creates_every_lead(client, session):
    _, tok, proj, _ = await _owner_project(client, session)
    pid, h = proj["id"], _auth(tok)
    r = await client.post(f"/projects/{pid}/lead-tokens", headers=h, json={"label": "site"})
    lt = {"X-Lead-Token": r.json()["token"]}

    rs = await asyncio.gather(*[
        client.post("/ingest/leads", headers=lt, json={"source": "site", "contact_name": f"№{i}"})
        for i in range(N)
    ])
    assert [r.status_code for r in rs] == [200] * N, [r.text for r in rs if r.status_code != 200]
    # каждая форма это новый лид, а не «повтор» чужого
    assert [r.json()["created"] for r in rs] == [True] * N
    assert len({r.json()["id"] for r in rs}) == N
    assert _numbers([r.json()["key"] for r in rs], "KL-L-") == list(range(1, N + 1))


@pytest.mark.asyncio
async def test_parallel_ingest_same_external_id_dedups(client, session):
    _, tok, proj, _ = await _owner_project(client, session)
    pid, h = proj["id"], _auth(tok)
    r = await client.post(f"/projects/{pid}/lead-tokens", headers=h, json={"label": "site"})
    lt = {"X-Lead-Token": r.json()["token"]}

    body = {"source": "site", "external_id": "form-42", "contact_name": "Иван"}
    rs = await asyncio.gather(
        *[client.post("/ingest/leads", headers=lt, json=body) for _ in range(6)]
    )
    assert [r.status_code for r in rs] == [200] * 6, [r.text for r in rs]
    assert len({r.json()["id"] for r in rs}) == 1
    assert sum(r.json()["created"] for r in rs) == 1
    # номер проигравших не съеден: следующий лид получает KL-L-2
    r = await client.post(f"/projects/{pid}/leads", headers=h, json={"title": "следующий"})
    assert r.json()["key"] == "KL-L-2"


@pytest.mark.asyncio
async def test_parallel_task_creates_get_unique_keys(client, session):
    _, tok, proj, _ = await _owner_project(client, session, enable=False)
    pid, h = proj["id"], _auth(tok)

    rs = await asyncio.gather(*[
        client.post("/tasks", headers=h, json={"project_id": pid, "title": f"задача {i}"})
        for i in range(N)
    ])
    assert [r.status_code for r in rs] == [201] * N, [r.text for r in rs if r.status_code != 201]
    assert _numbers([r.json()["key"] for r in rs], "KL-") == list(range(1, N + 1))
