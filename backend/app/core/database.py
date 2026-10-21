from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# The only way to inject the request session: `db: AsyncSession = DbSession`.
# scope="function" runs get_db's exit (commit / rollback) after the endpoint and response
# serialization but BEFORE the response is sent. FastAPI >= 0.121 defaults yield
# dependencies to scope="request", whose exit runs AFTER the response is sent: a client
# could get 201 and then 404 on its very next request, and a commit failure was invisible
# to it. Never use a bare Depends(get_db): scope is part of the dependency cache key, so
# mixing scopes opens two sessions per request. Guarded by tests/test_commit_before_response.py.
DbSession = Depends(get_db, scope="function")
