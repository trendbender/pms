"""Background worker placeholder.

Real jobs (notification fan-out, email delivery, due/overdue sweeps) arrive in
Sprint 7. For now this keeps the compose `worker` service alive and reachable so
the deployment topology is fixed from day one.
"""

import asyncio
import logging

from app.core.config import settings

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("worker")


async def main() -> None:
    log.info("Worker started (no jobs registered yet). Environment=%s", settings.environment)
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
