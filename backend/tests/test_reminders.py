"""Напоминания: арифметика расписания и срабатывание (движок вместо cron)."""

from datetime import UTC, date, datetime, time
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models.delivery import OutboxMessage, ProjectChannel
from app.models.enums import ReminderSchedule, ReminderStatus, SystemRole
from app.models.notification import Notification
from app.models.reminder import Reminder
from app.modules.reminders.schedule import next_fire_at
from app.modules.reminders.service import fire_due
from tests.factories import make_user, make_workspace

MSK = "Europe/Moscow"


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _setup(client, session, code="RMD", email="owner@rmd.ex"):
    """Владелец, проект, задача. Возвращает (workspace, user_id, token, project, task)."""
    ws = await make_workspace(session)
    user = await make_user(session, ws, email, SystemRole.OWNER)
    await session.commit()
    tok = await _token(client, email)
    r = await client.post("/projects", headers=_auth(tok), json={"name": "P", "code": code})
    assert r.status_code == 201, r.text
    project = r.json()
    r = await client.post(
        "/tasks",
        headers=_auth(tok),
        json={"project_id": project["id"], "title": "Сверить редполитику"},
    )
    assert r.status_code == 201, r.text
    return ws, user.id, tok, project, r.json()


async def _statuses(client, tok, project_id):
    r = await client.get(f"/projects/{project_id}/statuses", headers=_auth(tok))
    assert r.status_code == 200
    return {s["category"]: s for s in r.json()}


def _reminder(ws_id, project_id, task_id, **extra) -> Reminder:
    base = {
        "workspace_id": ws_id,
        "project_id": project_id,
        "task_id": task_id,
        "schedule": ReminderSchedule.DAILY,
        "at_time": time(10, 0),
        "timezone": MSK,
        "start_on": date(2026, 11, 4),
        "next_fire_at": datetime(2026, 11, 4, 7, 0, tzinfo=UTC),
        "status": ReminderStatus.ACTIVE,
    }
    return Reminder(**{**base, **extra})


# --------------------------------------------------------------------------- #
# Арифметика расписания (без базы)
# --------------------------------------------------------------------------- #


def test_daily_counts_in_the_reminders_timezone():
    """10:00 по Москве это 07:00 UTC, а не 10:00 на сервере."""
    moment = next_fire_at(
        schedule=ReminderSchedule.DAILY,
        at_time=time(10, 0),
        timezone=MSK,
        start_on=date(2026, 11, 4),
    )
    assert moment == datetime(2026, 11, 4, 7, 0, tzinfo=UTC)


def test_after_is_strict_so_a_slot_never_repeats():
    first = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)
    assert next_fire_at(
        schedule=ReminderSchedule.DAILY,
        at_time=time(10, 0),
        timezone=MSK,
        start_on=date(2026, 11, 4),
        after=first,
    ) == datetime(2026, 11, 5, 7, 0, tzinfo=UTC)


def test_once_is_exhausted_after_it_fired():
    first = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)
    assert next_fire_at(
        schedule=ReminderSchedule.ONCE,
        at_time=time(10, 0),
        timezone=MSK,
        start_on=date(2026, 11, 4),
        after=first,
    ) is None


def test_weekdays_skip_the_weekend():
    friday = datetime(2026, 11, 6, 7, 0, tzinfo=UTC)  # 6 ноября 2026 — пятница
    assert next_fire_at(
        schedule=ReminderSchedule.WEEKDAYS,
        at_time=time(10, 0),
        timezone=MSK,
        start_on=date(2026, 11, 4),
        after=friday,
    ) == datetime(2026, 11, 9, 7, 0, tzinfo=UTC)


def test_until_on_closes_the_schedule():
    assert next_fire_at(
        schedule=ReminderSchedule.DAILY,
        at_time=time(10, 0),
        timezone=MSK,
        start_on=date(2026, 11, 4),
        until_on=date(2026, 11, 4),
        after=datetime(2026, 11, 4, 7, 0, tzinfo=UTC),
    ) is None


def test_anchor_to_the_due_date_moves_the_reminder():
    """Напоминание «за два дня до срока» считается от срока, а не от start_on."""
    assert next_fire_at(
        schedule=ReminderSchedule.ONCE,
        at_time=time(10, 0),
        timezone=MSK,
        start_on=date(2026, 11, 4),
        anchor_date=date(2026, 11, 18),
    ) == datetime(2026, 11, 18, 7, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Срабатывание
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_fires_into_the_outbox_and_plans_the_next_one(client, session):
    ws, user_id, tok, project, task = await _setup(client, session)
    channel = ProjectChannel(
        workspace_id=ws.id,
        project_id=UUID(project["id"]),
        kind="TELEGRAM",
        name="Чат проекта",
        address="-1001234567890",
    )
    session.add(channel)
    await session.flush()
    session.add(
        _reminder(
            ws.id,
            UUID(project["id"]),
            UUID(task["id"]),
            channel_id=channel.id,
            notify_user_id=user_id,
            mention="@vanstallin",
        )
    )
    await session.commit()

    fired = await fire_due(session, datetime(2026, 11, 4, 7, 1, tzinfo=UTC))
    await session.commit()
    assert fired == 1

    message = (await session.scalars(select(OutboxMessage))).one()
    assert message.status == "PENDING"
    assert message.address == "-1001234567890"
    assert "@vanstallin" in message.body
    assert task["key"].lower() in message.body  # ссылка на задачу
    assert message.scheduled_for == datetime(2026, 11, 4, 7, 0, tzinfo=UTC)

    reminder = (await session.scalars(select(Reminder))).one()
    assert reminder.fire_count == 1
    assert reminder.next_fire_at == datetime(2026, 11, 5, 7, 0, tzinfo=UTC)
    assert reminder.status == ReminderStatus.ACTIVE

    note = (await session.scalars(select(Notification))).one()
    assert note.kind == "reminder"


@pytest.mark.asyncio
async def test_same_tick_twice_does_not_send_twice(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="RM2", email="o2@rmd.ex")
    session.add(_reminder(ws.id, UUID(project["id"]), UUID(task["id"]), notify_user_id=user_id))
    await session.commit()

    now = datetime(2026, 11, 4, 7, 1, tzinfo=UTC)
    assert await fire_due(session, now) == 1
    await session.commit()
    assert await fire_due(session, now) == 0
    await session.commit()


@pytest.mark.asyncio
async def test_closing_the_task_stops_the_reminder(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="RM3", email="o3@rmd.ex")
    session.add(_reminder(ws.id, UUID(project["id"]), UUID(task["id"]), notify_user_id=user_id))
    await session.commit()

    statuses = await _statuses(client, tok, project["id"])
    r = await client.patch(
        f"/tasks/{task['id']}/status",
        headers=_auth(tok),
        json={"status_id": statuses["DONE"]["id"]},
    )
    assert r.status_code == 200, r.text

    assert await fire_due(session, datetime(2026, 11, 4, 7, 1, tzinfo=UTC)) == 0
    await session.commit()

    reminder = (await session.scalars(select(Reminder))).one()
    assert reminder.status == ReminderStatus.COMPLETED
    assert reminder.stop_reason == "задача закрыта"
    assert reminder.next_fire_at is None
    assert (await session.scalars(select(OutboxMessage))).first() is None


@pytest.mark.asyncio
async def test_max_fires_closes_the_reminder(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="RM4", email="o4@rmd.ex")
    session.add(
        _reminder(
            ws.id, UUID(project["id"]), UUID(task["id"]), notify_user_id=user_id, max_fires=1
        )
    )
    await session.commit()

    assert await fire_due(session, datetime(2026, 11, 4, 7, 1, tzinfo=UTC)) == 1
    await session.commit()
    assert await fire_due(session, datetime(2026, 11, 5, 7, 1, tzinfo=UTC)) == 0
    await session.commit()

    reminder = (await session.scalars(select(Reminder))).one()
    assert reminder.status == ReminderStatus.COMPLETED
    assert reminder.stop_reason == "исчерпан лимит напоминаний"


@pytest.mark.asyncio
async def test_escalation_tells_the_owner_after_n_silent_reminders(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="RM5", email="o5@rmd.ex")
    chief = await make_user(session, ws, "chief@rmd.ex", SystemRole.OWNER)
    await session.flush()
    session.add(
        _reminder(
            ws.id,
            UUID(project["id"]),
            UUID(task["id"]),
            notify_user_id=user_id,
            escalate_after_fires=2,
            escalate_to_id=chief.id,
        )
    )
    await session.commit()

    await fire_due(session, datetime(2026, 11, 4, 7, 1, tzinfo=UTC))
    await session.commit()
    assert (
        await session.scalars(select(Notification).where(Notification.user_id == chief.id))
    ).first() is None

    await fire_due(session, datetime(2026, 11, 5, 7, 1, tzinfo=UTC))
    await session.commit()
    escalated = (
        await session.scalars(select(Notification).where(Notification.user_id == chief.id))
    ).one()
    assert escalated.kind == "reminder.escalated"


@pytest.mark.asyncio
async def test_a_reminder_without_a_channel_stays_inside_pms(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="RM6", email="o6@rmd.ex")
    session.add(_reminder(ws.id, UUID(project["id"]), UUID(task["id"]), notify_user_id=user_id))
    await session.commit()

    assert await fire_due(session, datetime(2026, 11, 4, 7, 1, tzinfo=UTC)) == 1
    await session.commit()
    assert (await session.scalars(select(OutboxMessage))).first() is None
    assert (await session.scalars(select(Notification))).one().kind == "reminder"


# --------------------------------------------------------------------------- #
# API: кто что может и что двигает сроки
# --------------------------------------------------------------------------- #


async def _member(client, session, ws, project_id, tok, email="member@rmd.ex", role="MEMBER"):
    user = await make_user(session, ws, email, SystemRole.MEMBER)
    await session.commit()
    r = await client.post(
        f"/projects/{project_id}/members",
        headers=_auth(tok),
        json={"user_id": str(user.id), "role": role},
    )
    assert r.status_code in (200, 201), r.text
    return user, await _token(client, email)


@pytest.mark.asyncio
async def test_create_reminder_through_the_api(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="AP1", email="a1@rmd.ex")
    r = await client.post(
        f"/tasks/{task['id']}/reminders",
        headers=_auth(tok),
        json={
            "schedule": "DAILY",
            "at_time": "10:00:00",
            "start_on": "2099-01-04",
            "stop_on_done": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "ACTIVE"
    assert body["next_fire_at"].startswith("2099-01-04T07:00")  # 10:00 МСК
    assert body["task_key"] == task["key"]
    assert body["log"] == []


@pytest.mark.asyncio
async def test_a_moment_in_the_past_is_refused(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="AP2", email="a2@rmd.ex")
    r = await client.post(
        f"/tasks/{task['id']}/reminders",
        headers=_auth(tok),
        json={"schedule": "ONCE", "start_on": "2020-01-01"},
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_member_may_remind_in_pms_but_not_into_the_project_chat(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="AP3", email="a3@rmd.ex")
    r = await client.post(
        f"/projects/{project['id']}/channels",
        headers=_auth(tok),
        json={"name": "Чат проекта", "address": "-1001234567890", "is_default": True},
    )
    assert r.status_code == 201, r.text
    channel = r.json()

    _, member_tok = await _member(client, session, ws, project["id"], tok)

    inside = await client.post(
        f"/tasks/{task['id']}/reminders",
        headers=_auth(member_tok),
        json={"schedule": "ONCE", "start_on": "2099-01-04"},
    )
    assert inside.status_code == 201, inside.text

    outside = await client.post(
        f"/tasks/{task['id']}/reminders",
        headers=_auth(member_tok),
        json={"schedule": "ONCE", "start_on": "2099-01-04", "channel_id": channel["id"]},
    )
    assert outside.status_code == 403
    assert "reminder.external" in outside.json()["detail"]


@pytest.mark.asyncio
async def test_snooze_and_stop(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="AP4", email="a4@rmd.ex")
    r = await client.post(
        f"/tasks/{task['id']}/reminders",
        headers=_auth(tok),
        json={"schedule": "DAILY", "start_on": "2099-01-04"},
    )
    reminder = r.json()

    r = await client.post(
        f"/reminders/{reminder['id']}/snooze", headers=_auth(tok), json={"days": 3}
    )
    assert r.status_code == 200, r.text
    assert r.json()["next_fire_at"].startswith("2099-01-07T07:00")

    r = await client.post(f"/reminders/{reminder['id']}/stop", headers=_auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANCELLED"
    assert r.json()["next_fire_at"] is None


@pytest.mark.asyncio
async def test_moving_the_due_date_moves_the_anchored_reminder(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="AP5", email="a5@rmd.ex")
    r = await client.patch(
        f"/tasks/{task['id']}", headers=_auth(tok), json={"due_at": "2099-03-10T09:00:00Z"}
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/tasks/{task['id']}/reminders",
        headers=_auth(tok),
        json={"schedule": "ONCE", "due_offset_days": -2},
    )
    assert r.status_code == 201, r.text
    assert r.json()["next_fire_at"].startswith("2099-03-08T07:00")

    r = await client.patch(
        f"/tasks/{task['id']}", headers=_auth(tok), json={"due_at": "2099-03-17T09:00:00Z"}
    )
    assert r.status_code == 200, r.text

    moved = (await session.scalars(select(Reminder))).one()
    await session.refresh(moved)
    assert moved.next_fire_at == datetime(2099, 3, 15, 7, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_the_relay_takes_the_queue_and_marks_it_sent(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="AP6", email="a6@rmd.ex")
    channel = ProjectChannel(
        workspace_id=ws.id,
        project_id=UUID(project["id"]),
        kind="TELEGRAM",
        name="Чат",
        address="-100500",
    )
    session.add(channel)
    await session.flush()
    session.add(
        _reminder(
            ws.id,
            UUID(project["id"]),
            UUID(task["id"]),
            channel_id=channel.id,
            notify_user_id=user_id,
        )
    )
    await session.commit()
    await fire_due(session, datetime(2026, 11, 4, 7, 1, tzinfo=UTC))
    await session.commit()

    r = await client.get("/outbox/pending", headers=_auth(tok))
    assert r.status_code == 200, r.text
    queue = r.json()
    assert len(queue) == 1
    assert queue[0]["address"] == "-100500"

    r = await client.post(f"/outbox/{queue[0]['id']}/sent", headers=_auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SENT"

    assert (await client.get("/outbox/pending", headers=_auth(tok))).json() == []


@pytest.mark.asyncio
async def test_a_failed_send_stays_in_the_queue_until_attempts_run_out(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="AP7", email="a7@rmd.ex")
    channel = ProjectChannel(
        workspace_id=ws.id,
        project_id=UUID(project["id"]),
        kind="TELEGRAM",
        name="Чат",
        address="-100501",
    )
    session.add(channel)
    await session.flush()
    session.add(
        _reminder(
            ws.id,
            UUID(project["id"]),
            UUID(task["id"]),
            channel_id=channel.id,
            notify_user_id=user_id,
        )
    )
    await session.commit()
    await fire_due(session, datetime(2026, 11, 4, 7, 1, tzinfo=UTC))
    await session.commit()

    message_id = (await client.get("/outbox/pending", headers=_auth(tok))).json()[0]["id"]
    for attempt in (1, 2):
        r = await client.post(
            f"/outbox/{message_id}/failed", headers=_auth(tok), params={"error": "таймаут"}
        )
        assert r.json()["status"] == "PENDING", attempt
    r = await client.post(
        f"/outbox/{message_id}/failed", headers=_auth(tok), params={"error": "таймаут"}
    )
    assert r.json()["status"] == "FAILED"
    assert r.json()["attempts"] == 3


@pytest.mark.asyncio
async def test_snooze_without_a_timezone_means_the_reminders_timezone(client, session):
    ws, user_id, tok, project, task = await _setup(client, session, code="AP8", email="a8@rmd.ex")
    r = await client.post(
        f"/tasks/{task['id']}/reminders",
        headers=_auth(tok),
        json={"schedule": "DAILY", "start_on": "2099-01-04", "timezone": MSK},
    )
    reminder = r.json()
    r = await client.post(
        f"/reminders/{reminder['id']}/snooze",
        headers=_auth(tok),
        json={"until": "2099-01-09T09:00:00"},
    )
    assert r.status_code == 200, r.text
    # 09:00 по Москве, а не по часам сервера (тот же момент, что 06:00 UTC)
    assert datetime.fromisoformat(r.json()["next_fire_at"]) == datetime(
        2099, 1, 9, 6, 0, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_once_fires_once_even_after_a_snooze_into_the_past(client, session):
    """Перенос «на сейчас» не должен оставлять исходный момент впереди."""
    ws, user_id, tok, project, task = await _setup(client, session, code="AP9", email="a9@rmd.ex")
    session.add(
        _reminder(
            ws.id,
            UUID(project["id"]),
            UUID(task["id"]),
            notify_user_id=user_id,
            schedule=ReminderSchedule.ONCE,
            start_on=date(2026, 11, 30),
            # сработает раньше своего дня — как после snooze в прошлое
            next_fire_at=datetime(2026, 11, 4, 7, 0, tzinfo=UTC),
        )
    )
    await session.commit()

    assert await fire_due(session, datetime(2026, 11, 4, 7, 1, tzinfo=UTC)) == 1
    await session.commit()

    reminder = (await session.scalars(select(Reminder))).one()
    assert reminder.fire_count == 1
    assert reminder.next_fire_at is None
    assert reminder.status == ReminderStatus.COMPLETED
