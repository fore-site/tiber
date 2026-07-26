from collections.abc import AsyncGenerator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import AsyncSessionFactory
from ..core.redis import get_redis_client

settings = get_settings()


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield an AsyncSession per request, roll back on error, always close.

    Use as: db: AsyncSession = Depends(get_db).
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> AsyncGenerator[Redis]:
    """Yield a Redis client per request.

    Use as: redis: Redis = Depends(get_redis)
    """
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()
