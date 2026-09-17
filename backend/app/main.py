from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.redis import ping_redis
from app.modules.attachments.router import router as attachments_router
from app.modules.auth.router import router as auth_router
from app.modules.comments.router import router as comments_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.initiatives.router import router as initiatives_router
from app.modules.notifications.router import router as notifications_router
from app.modules.projects.router import router as projects_router
from app.modules.search.router import router as search_router
from app.modules.sprints.router import router as sprints_router
from app.modules.tasks.router import router as tasks_router
from app.modules.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Agile Project Operating System",
    version="0.1.0",
    description="Scrumban PMS — modular monolith (MVP, Sprints 1–7)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(comments_router)
app.include_router(attachments_router)
app.include_router(initiatives_router)
app.include_router(sprints_router)
app.include_router(dashboard_router)
app.include_router(notifications_router)
app.include_router(search_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Liveness + dependency checks (API, PostgreSQL, Redis)."""
    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    redis_ok = await ping_redis()
    status = "ok" if (db_ok and redis_ok) else "degraded"
    return {
        "status": status,
        "environment": settings.environment,
        "checks": {"api": True, "postgres": db_ok, "redis": redis_ok},
    }
