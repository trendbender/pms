"""Деньги проекта: договоры, платежи, календарь, доступ."""

from datetime import date, timedelta

import pytest

from app.models.enums import ProjectRole, SystemRole
from tests.factories import make_user, make_workspace


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _owner(client, session, code="FIN"):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, "owner@ex.com")
    r = await client.post("/projects", headers=_auth(tok), json={"name": "P", "code": code})
    assert r.status_code == 201, r.text
    return ws, tok, r.json()


async def _payment(client, tok, project_id, **body):
    payload = {"title": "Этап 1", "amount": "45000.00"} | body
    r = await client.post(
        f"/projects/{project_id}/payments", headers=_auth(tok), json=payload
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_payment_lifecycle(client, session):
    _, tok, proj = await _owner(client, session, code="PAY")
    due = (date.today() + timedelta(days=10)).isoformat()
    pay = await _payment(client, tok, proj["id"], due_date=due, kind="PREPAY")
    assert pay["status"] == "EXPECTED"
    assert pay["is_overdue"] is False
    assert pay["project_code"] == "PAY"

    r = await client.post(
        f"/finance/payments/{pay['id']}/invoice",
        headers=_auth(tok),
        json={"invoice_no": "44"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "INVOICED"
    assert r.json()["invoice_no"] == "44"
    assert r.json()["invoiced_at"] == date.today().isoformat()

    r = await client.post(
        f"/finance/payments/{pay['id']}/paid", headers=_auth(tok), json={"act_no": "44"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PAID"
    assert r.json()["paid_at"] == date.today().isoformat()


@pytest.mark.asyncio
async def test_overdue_is_derived_not_stored(client, session):
    _, tok, proj = await _owner(client, session, code="OVD")
    past = (date.today() - timedelta(days=3)).isoformat()
    pay = await _payment(client, tok, proj["id"], due_date=past, amount="10000")
    assert pay["is_overdue"] is True
    # статус в базе остаётся EXPECTED: просрочку считаем, а не переписываем
    assert pay["status"] == "EXPECTED"

    r = await client.get("/finance/calendar", headers=_auth(tok))
    assert r.status_code == 200, r.text
    cal = r.json()
    assert [p["id"] for p in cal["overdue"]] == [pay["id"]]
    assert cal["total_overdue"] == "10000.00"
    assert cal["by_project"][0]["code"] == "OVD"
    assert cal["by_project"][0]["overdue"] == "10000.00"

    # оплаченный платёж уходит из просрочки
    await client.post(f"/finance/payments/{pay['id']}/paid", headers=_auth(tok), json={})
    cal = (await client.get("/finance/calendar", headers=_auth(tok))).json()
    assert cal["overdue"] == []
    assert cal["by_project"][0]["paid_total"] == "10000.00"


@pytest.mark.asyncio
async def test_calendar_buckets_and_forecast(client, session):
    _, tok, proj = await _owner(client, session, code="CAL")
    soon = (date.today() + timedelta(days=3)).isoformat()
    later = (date.today() + timedelta(days=20)).isoformat()
    far = (date.today() + timedelta(days=200)).isoformat()
    await _payment(client, tok, proj["id"], due_date=soon, amount="1000", title="скоро")
    await _payment(client, tok, proj["id"], due_date=later, amount="2000", title="позже")
    await _payment(client, tok, proj["id"], due_date=far, amount="5000", title="далеко")

    cal = (await client.get("/finance/calendar", headers=_auth(tok))).json()
    assert [p["title"] for p in cal["due_soon"]] == ["скоро"]
    assert [p["title"] for p in cal["upcoming"]] == ["позже"]
    # прогноз на 4 недели берёт только то, что попадает в горизонт
    assert cal["forecast_amount"] == "3000.00"
    assert cal["total_open"] == "8000.00"


@pytest.mark.asyncio
async def test_unbilled_milestone_surfaces(client, session):
    _, tok, proj = await _owner(client, session, code="UNB")
    r = await client.post(
        f"/projects/{proj['id']}/initiatives",
        headers=_auth(tok),
        json={"name": "Веха 1", "due_date": (date.today() - timedelta(days=1)).isoformat()},
    )
    assert r.status_code == 201, r.text
    ini = r.json()
    assert ini["due_date"] == (date.today() - timedelta(days=1)).isoformat()

    pay = await _payment(
        client,
        tok,
        proj["id"],
        initiative_id=ini["id"],
        due_date=(date.today() - timedelta(days=1)).isoformat(),
        amount="30000",
    )
    cal = (await client.get("/finance/calendar", headers=_auth(tok))).json()
    assert [p["id"] for p in cal["unbilled_milestones"]] == [pay["id"]]

    # выставили счёт — веха перестаёт быть забытой
    await client.post(
        f"/finance/payments/{pay['id']}/invoice", headers=_auth(tok), json={"invoice_no": "7"}
    )
    cal = (await client.get("/finance/calendar", headers=_auth(tok))).json()
    assert cal["unbilled_milestones"] == []


@pytest.mark.asyncio
async def test_member_cannot_see_money(client, session):
    ws, tok, proj = await _owner(client, session, code="SEC")
    await _payment(client, tok, proj["id"], amount="99000")
    member = await make_user(session, ws, "member@ex.com", SystemRole.MEMBER)
    await session.commit()
    r = await client.post(
        f"/projects/{proj['id']}/members",
        headers=_auth(tok),
        json={"user_id": str(member.id), "role": ProjectRole.MEMBER.value},
    )
    assert r.status_code in (200, 201), r.text

    mtok = await _token(client, "member@ex.com")
    # участник проекта видит доску, но не деньги
    assert (await client.get(f"/projects/{proj['id']}", headers=_auth(mtok))).status_code == 200
    r = await client.get(f"/projects/{proj['id']}/payments", headers=_auth(mtok))
    assert r.status_code == 403, r.text
    cal = (await client.get("/finance/calendar", headers=_auth(mtok))).json()
    assert cal["by_project"] == []
    assert (await client.get("/finance/payments", headers=_auth(mtok))).json() == []


@pytest.mark.asyncio
async def test_contract_and_cross_project_link_rejected(client, session):
    _, tok, proj = await _owner(client, session, code="CTR")
    r = await client.post(
        f"/projects/{proj['id']}/contracts",
        headers=_auth(tok),
        json={"title": "Договор 06/07-2026", "kind": "HOURLY", "rate": "2500"},
    )
    assert r.status_code == 201, r.text
    contract = r.json()
    assert contract["kind"] == "HOURLY"
    assert contract["currency"] == "RUB"

    other = await client.post(
        "/projects", headers=_auth(tok), json={"name": "Other", "code": "OTH"}
    )
    r = await client.post(
        f"/projects/{other.json()['id']}/payments",
        headers=_auth(tok),
        json={"title": "чужой счёт", "amount": "100", "contract_id": contract["id"]},
    )
    assert r.status_code == 400, r.text
