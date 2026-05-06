from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from agent_routers.services.session_manager import SessionManager


@pytest.fixture
def mock_redis():
    with patch("agent_routers.services.session_manager.redis.from_url") as mock_from_url:
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
async def test_get_route_found(mock_redis):
    mock_redis.get.return_value = "agent-1"
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_route("sess-123")
    assert result == "agent-1"
    mock_redis.get.assert_awaited_once_with("session:sess-123")


@pytest.mark.asyncio
async def test_get_route_not_found(mock_redis):
    mock_redis.get.return_value = None
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_route("sess-123")
    assert result is None


@pytest.mark.asyncio
async def test_get_route_empty_session_id(mock_redis):
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_route("")
    assert result is None
    mock_redis.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_route(mock_redis):
    mgr = SessionManager("redis://localhost")
    await mgr.set_route("sess-123", "agent-1", ttl=3600)
    mock_redis.set.assert_awaited_once_with("session:sess-123", "agent-1", ex=3600)


@pytest.mark.asyncio
async def test_set_route_empty_session_id(mock_redis):
    mgr = SessionManager("redis://localhost")
    await mgr.set_route("", "agent-1")
    mock_redis.set.assert_not_awaited()
