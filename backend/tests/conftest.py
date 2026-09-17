import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Point the app at the test database BEFORE app modules read settings.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql+asyncpg://pms@127.0.0.1:5599/pms_test"),
)
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("JWT_SECRET", "test_secret")

from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

_engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
_Session = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def _schema():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _override_get_db():
    async with _Session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def session():
    async with _Session() as s:
        yield s
        await s.commit()
