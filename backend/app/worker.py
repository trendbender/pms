"""Фоновый воркер: тик раз в минуту, напоминания.

Воркер ничего не решает сам — он будит доменную логику. Расписание, условия
остановки и адреса живут в базе, здесь только цикл и его живучесть: упавший
тик не роняет процесс, следующая минута пробует снова.

Отправкой наружу воркер тоже не занимается: он кладёт сообщение в
`outbox_messages`, а забирает его релей на стороне бота (решение T-003).
"""

import asyncio
import logging
from datetime import UTC, datetime

from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.reminders.service import fire_due

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("worker")

TICK_SECONDS = 60


async def tick() -> int:
    """Один проход: отработать напоминания, которым пора."""
    async with SessionLocal() as db:
        fired = await fire_due(db, datetime.now(UTC))
        await db.commit()
    return fired


async def main() -> None:
    log.info("Worker started. Environment=%s, tick=%ss", settings.environment, TICK_SECONDS)
    while True:
        try:
            fired = await tick()
            if fired:
                log.info("Напоминаний отправлено: %s", fired)
        except Exception:  # один плохой тик не должен уносить воркер
            log.exception("Тик воркера упал")
        await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
