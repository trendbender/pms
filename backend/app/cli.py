"""Tiny management CLI.

Usage:
    python -m app.cli seed     # create bootstrap workspace + Owner if absent
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.enums import SystemRole
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


async def seed() -> None:
    async with SessionLocal() as db:
        email = settings.bootstrap_owner_email.lower()
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is not None:
            print(f"Owner {email} already exists — nothing to seed.")
            return

        ws = Workspace(name=settings.bootstrap_workspace_name)
        db.add(ws)
        await db.flush()

        owner = User(
            email=email,
            name=settings.bootstrap_owner_name,
            password_hash=hash_password(settings.bootstrap_owner_password),
        )
        db.add(owner)
        await db.flush()

        db.add(
            WorkspaceMember(
                workspace_id=ws.id, user_id=owner.id, system_role=SystemRole.OWNER.value
            )
        )
        await db.commit()
        print(f"Seeded workspace '{ws.name}' and Owner {email}.")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "seed":
        print(__doc__)
        sys.exit(1)
    asyncio.run(seed())


if __name__ == "__main__":
    main()
