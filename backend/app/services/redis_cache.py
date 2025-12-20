import redis.asyncio as redis
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class RedisClient:
    _client = None

    @classmethod
    async def get_client(cls):
        if cls._client is None:
            try:
                cls._client = redis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
                await cls._client.ping()
                logger.info("Redis connection established")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                cls._client = None
        return cls._client

    @classmethod
    async def get(cls, key: str):
        client = await cls.get_client()
        if client:
            try:
                return await client.get(key)
            except Exception as e:
                logger.error(f"Redis get error: {e}")
        return None

    @classmethod
    async def set(cls, key: str, value: str, expire: int = None):
        client = await cls.get_client()
        if client:
            try:
                await client.set(key, value, ex=expire)
            except Exception as e:
                logger.error(f"Redis set error: {e}")

    @classmethod
    async def incr(cls, key: str, expire: int = None):
        client = await cls.get_client()
        if client:
            try:
                pipe = client.pipeline()
                pipe.incr(key)
                if expire:
                    pipe.expire(key, expire)
                await pipe.execute()
            except Exception as e:
                logger.error(f"Redis incr error: {e}")

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.close()
            cls._client = None
