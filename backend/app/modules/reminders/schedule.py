"""Когда напоминание сработает в следующий раз.

Чистая арифметика без базы: на вход расписание, на выход момент в UTC. Так её
видно в тестах целиком, без поднятия приложения.

Два правила, которые легко потерять:

* считаем в часовом поясе напоминания, а не сервера. «Каждый день в 10:00»
  означает 10 утра у человека, которому напоминают, и переход на зимнее время
  не должен сдвигать это на час — поэтому дата и время собираются в tz, и
  только потом переводятся в UTC.
* `after` это «строго позже». Передаём момент прошлого срабатывания, и
  следующее никогда не попадёт на тот же слот: повторов на одну и ту же дату
  не будет, даже если воркер проснулся дважды.

Рабочие дни здесь — это пн-пт. Производственный календарь РФ (переносы и
праздники) живёт отдельным скриптом на другой машине; подключим его, когда
напоминания по рабочим дням начнут попадать на праздники.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models.enums import ReminderSchedule

# Предохранитель от бесконечного цикла: расписание, которое не нашло день за
# год с лишним, считается исчерпанным.
MAX_LOOKAHEAD_DAYS = 400


def at_moment(day: date, at: time, tz: ZoneInfo) -> datetime:
    """Дата и время в часовом поясе напоминания → момент в UTC."""
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def _day_matches(schedule: str, day: date, weekday: int | None, base: date) -> bool:
    if schedule == ReminderSchedule.DAILY:
        return True
    if schedule == ReminderSchedule.WEEKDAYS:
        return day.weekday() < 5
    if schedule == ReminderSchedule.WEEKLY:
        return day.weekday() == (weekday if weekday is not None else base.weekday())
    return False


def next_fire_at(
    *,
    schedule: str,
    at_time: time,
    timezone: str,
    start_on: date,
    weekday: int | None = None,
    until_on: date | None = None,
    after: datetime | None = None,
    anchor_date: date | None = None,
) -> datetime | None:
    """Следующее срабатывание строго позже `after`, или None — расписание кончилось.

    `anchor_date` — дата, посчитанная от срока задачи (напоминание «за два дня
    до срока»). Если она задана, расписание отсчитывается от неё, а не от
    `start_on`: перенос срока двигает и напоминание.
    """
    tz = ZoneInfo(timezone)
    base = anchor_date or start_on

    if schedule == ReminderSchedule.ONCE:
        if until_on and base > until_on:
            return None
        fire = at_moment(base, at_time, tz)
        return None if after is not None and fire <= after else fire

    day = base
    if after is not None:
        after_day = after.astimezone(tz).date()
        if after_day > day:
            day = after_day

    for _ in range(MAX_LOOKAHEAD_DAYS):
        if until_on and day > until_on:
            return None
        if _day_matches(schedule, day, weekday, base):
            fire = at_moment(day, at_time, tz)
            if after is None or fire > after:
                return fire
        day += timedelta(days=1)
    return None
