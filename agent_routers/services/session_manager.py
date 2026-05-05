from __future__ import annotations

import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)

DEFAULT_TTL = 86400  # 24 hours


class SessionManager:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    async def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def get_route(self, session_id: str) -> tuple[str, str] | None:
        if not session_id:
            return None
        try:
            client = await self._ensure_client()
            value = await client.get(f"session:{session_id}")
            if value:
                parts = value.split(":", 1)
                if len(parts) == 2:
                    return parts[0], parts[1]
            return None
        except Exception:
            logger.exception("session_get_failed", extra={"session_id": session_id})
            return None

    async def set_route(
        self,
        session_id: str,
        agent_id: str,
        endpoint_id: str,
        ttl: int = DEFAULT_TTL,
    ) -> None:
        if not session_id or not agent_id or not endpoint_id:
            return
        try:
            client = await self._ensure_client()
            value = f"{agent_id}:{endpoint_id}"
            await client.set(f"session:{session_id}", value, ex=ttl)
            logger.info("session_set", extra={"session_id": session_id, "agent_id": agent_id, "endpoint_id": endpoint_id})
        except Exception:
            logger.exception("session_set_failed", extra={"session_id": session_id, "agent_id": agent_id})
