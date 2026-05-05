from __future__ import annotations

import time
import logging

import redis.asyncio as redis

from agent_routers.config.settings import settings

logger = logging.getLogger(__name__)

QUOTA_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local score = now * 1000 + tonumber(ARGV[4])

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window * 1000)
local count = redis.call('ZCARD', key)
if count >= limit then
    return -1
end
redis.call('ZADD', key, score, score)
redis.call('EXPIRE', key, window)
return 1
"""

QUOTA_SCRIPT_SHA: str | None = None


class QuotaExceeded(Exception):
    pass


class RedisQuota:
    def __init__(self, redis_url: str, limit: int = 120, window_seconds: int = 60):
        self._url = redis_url
        self._limit = limit
        self._window = window_seconds
        self._client: redis.Redis | None = None
        self._script_sha: str | None = None

    async def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._url, decode_responses=True)
            sha = await self._client.script_load(QUOTA_LUA)
            self._script_sha = sha
        return self._client

    async def check(self, subject: str) -> bool:
        client = await self._ensure_client()
        key = f"quota:{subject}"
        now_ms = int(time.time() * 1000)
        micro = now_ms % 1000

        args = [str(int(time.time())), str(self._window), str(self._limit), str(micro)]
        try:
            result = await client.evalsha(self._script_sha or "", 1, key, *args)
        except redis.ResponseError:
            result = await client.eval(QUOTA_LUA, 1, key, *args)
            self._script_sha = await client.script_load(QUOTA_LUA)

        if result == -1:
            raise QuotaExceeded(f"Quota exceeded for {subject}")
        return True

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


_quota_instance: RedisQuota | None = None


def get_quota() -> RedisQuota:
    global _quota_instance
    if _quota_instance is None:
        _quota_instance = RedisQuota(settings.REDIS_URL, settings.QUOTA_DEFAULT_PER_MINUTE)
    return _quota_instance
