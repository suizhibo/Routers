from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)


class PerAgentClientPool:
    CONNECTOR_KW = dict(
        limit=50,
        limit_per_host=20,
        keepalive_timeout=60.0,
    )
    TIMEOUT = aiohttp.ClientTimeout(
        sock_connect=2.0,
        sock_read=30.0,
        total=None,
    )

    def __init__(self) -> None:
        self._sessions: dict[str, aiohttp.ClientSession] = {}

    def create(self, agent_id: str, base_url: str) -> aiohttp.ClientSession:
        if agent_id in self._sessions:
            raise ValueError(f"Client for agent '{agent_id}' already exists")
        connector = aiohttp.TCPConnector(**self.CONNECTOR_KW)
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=self.TIMEOUT,
        )
        self._sessions[agent_id] = session
        logger.info("agent_client_created", extra={"agent_id": agent_id, "base_url": base_url})
        return session

    def get(self, agent_id: str) -> aiohttp.ClientSession | None:
        return self._sessions.get(agent_id)

    def destroy(self, agent_id: str) -> None:
        session = self._sessions.pop(agent_id, None)
        if session is not None:
            logger.info("agent_client_destroyed", extra={"agent_id": agent_id})

    async def close_all(self) -> None:
        for _agent_id, session in list(self._sessions.items()):
            await session.close()
        self._sessions.clear()


_client_pool: PerAgentClientPool | None = None


def get_client_pool() -> PerAgentClientPool:
    global _client_pool
    if _client_pool is None:
        _client_pool = PerAgentClientPool()
    return _client_pool
