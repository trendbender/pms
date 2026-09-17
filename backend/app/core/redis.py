from redis.asyncio import Redis

from app.core.config import settings

redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def ping_redis() -> bool:
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False
