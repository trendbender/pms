"""Сессия коммитится ДО отправки ответа (регрессия 19.10.2026).

С FastAPI >= 0.121 зависимость с yield по умолчанию (scope="request") закрывается
ПОСЛЕ отправки ответа. get_db коммитил в этой фазе, и клиент, получивший 201 и сразу
пришедший следующим запросом, ловил 404 на только что созданную строку
(site-leads-api.py: ingest -> `pms.py lead comment`; pms.py: add -> status).

httpx.ASGITransport ждёт полного завершения ASGI-вызова, включая фазу после ответа,
поэтому гонку «201, потом 404» в этом клиенте не увидеть: create->read тут зелёный и до
фикса. Сам баг ловят два теста ниже: порядок событий commit / http.response.start и
обход всех роутов на scope="function". На живом uvicorn проверено отдельно (см. CHANGELOG).
"""

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app
from tests.test_leads import _auth, _owner_project


def _api_routes(routes):
    # FastAPI 0.14x хранит include_router лениво (_IncludedRouter), а не плоским списком
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif (inner := getattr(route, "original_router", None)) is not None:
            yield from _api_routes(inner.routes)


def _get_db_dependants(dependant):
    for dep in dependant.dependencies:
        if dep.call is get_db:
            yield dep
        yield from _get_db_dependants(dep)


def test_every_route_closes_db_session_before_response():
    """Каждый Depends(get_db) во всех роутах должен быть scope="function".

    Голый Depends(get_db) вернёт коммит после ответа, а смешение скоупов даст две
    разные сессии в одном запросе (scope входит в ключ кэша зависимостей).
    """
    checked, wrong = 0, []
    for route in _api_routes(app.routes):
        for dep in _get_db_dependants(route.dependant):
            checked += 1
            if dep.scope != "function":
                wrong.append(f"{sorted(route.methods)} {route.path}: scope={dep.scope!r}")
    assert checked > 100, checked
    assert wrong == []


@pytest.mark.asyncio
async def test_create_then_read_immediately(client, session):
    _, tok, proj, _ = await _owner_project(client, session)
    pid, h = proj["id"], _auth(tok)

    # лид руками -> сразу GET и комментарий
    r = await client.post(f"/projects/{pid}/leads", headers=h, json={"title": "Срочный лид"})
    assert r.status_code == 201, r.text
    lead_id = r.json()["id"]
    assert (await client.get(f"/leads/{lead_id}", headers=h)).status_code == 200
    r = await client.post(f"/leads/{lead_id}/comments", headers=h, json={"text": "из формы"})
    assert r.status_code == 201, r.text

    # путь site-leads-api: ingest по ключу -> сразу комментарий по key
    r = await client.post(f"/projects/{pid}/lead-tokens", headers=h, json={"label": "site"})
    raw = r.json()["token"]
    r = await client.post(
        "/ingest/leads", headers={"X-Lead-Token": raw},
        json={"source": "site", "external_id": "form-1", "contact_name": "Иван"},
    )
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    r = await client.get(f"/leads/by-key/{key}", headers=h)
    assert r.status_code == 200, r.text
    r = await client.post(f"/leads/{r.json()['id']}/comments", headers=h, json={"text": "форма"})
    assert r.status_code == 201, r.text

    # задача -> сразу GET и комментарий (pms.py add -> status / comment)
    r = await client.post("/tasks", headers=h, json={"project_id": pid, "title": "Позвонить"})
    assert r.status_code == 201, r.text
    task = r.json()
    assert (await client.get(f"/tasks/{task['id']}", headers=h)).status_code == 200
    assert (await client.get(f"/tasks/by-key/{task['key']}", headers=h)).status_code == 200
    r = await client.post(f"/tasks/{task['id']}/comments", headers=h, json={"body": "ок"})
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_commit_happens_before_response_start(client, session, monkeypatch):
    """Через override из conftest: тот же порядок, что и у боевого get_db."""
    _, tok, proj, _ = await _owner_project(client, session)
    pid, h = proj["id"], _auth(tok)

    events: list[str] = []
    real_commit = AsyncSession.commit

    async def recording_commit(self):
        await real_commit(self)
        events.append("commit")

    monkeypatch.setattr(AsyncSession, "commit", recording_commit)

    async def recording_app(scope, receive, send):
        async def _send(message):
            if message["type"] == "http.response.start":
                events.append(f"response.start {message['status']}")
            await send(message)

        await app(scope, receive, _send)

    async with AsyncClient(
        transport=ASGITransport(app=recording_app), base_url="http://test"
    ) as c:
        for method, url, body in [
            ("POST", f"/projects/{pid}/leads", {"title": "Лид"}),
            ("POST", "/tasks", {"project_id": pid, "title": "Задача"}),
        ]:
            events.clear()
            r = await c.request(method, url, headers=h, json=body)
            assert r.status_code == 201, r.text
            assert events == ["commit", "response.start 201"], (url, events)
