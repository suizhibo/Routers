from __future__ import annotations

import httpx
import logging

logger = logging.getLogger(__name__)


class PerAgentClientPool:
    LIMITS = httpx.Limits(
        max_connections=50,
        max_keepalive_connections=20,
        keepalive_expiry=60.0,
    )
    TIMEOUT = httpx.Timeout(
        connect=2.0,
        read=30.0,
        write=10.0,
        pool=5.0,
    )

    def __init__(self):
        self._clients: dict[str, httpx.AsyncClient] = {}

    def create(self, agent_id: str, base_url: str) -> httpx.AsyncClient:
        if agent_id in self._clients:
            raise ValueError(f"Client for agent '{agent_id}' already exists")
        client = httpx.AsyncClient(
            base_url=base_url,
            limits=self.LIMITS,
            timeout=self.TIMEOUT,
            follow_redirects=True,
        )
        self._clients[agent_id] = client
        logger.info("agent_client_created", extra={"agent_id": agent_id, "base_url": base_url})
        return client

    def get(self, agent_id: str) -> httpx.AsyncClient | None:
        return self._clients.get(agent_id)

    def destroy(self, agent_id: str) -> None:
        client = self._clients.pop(agent_id, None)
        if client:
            logger.info("agent_client_destroyed", extra={"agent_id": agent_id})

    async def close_all(self) -> None:
        for agent_id, client in list(self._clients.items()):
            await client.aclose()
        self._clients.clear()


_client_pool: PerAgentClientPool | None = None


def get_client_pool() -> PerAgentClientPool:
    global _client_pool
    if _client_pool is None:
        _client_pool = PerAgentClientPool()
    return _client_pool
