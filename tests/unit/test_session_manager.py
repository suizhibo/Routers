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
async def test_get_instance_found(mock_redis):
    mock_redis.get.return_value = "inst-a"
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_instance("agent-1", "sess-123")
    assert result == "inst-a"
    mock_redis.get.assert_awaited_once_with("session:agent-1:sess-123")


@pytest.mark.asyncio
async def test_get_instance_not_found(mock_redis):
    mock_redis.get.return_value = None
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_instance("agent-1", "sess-123")
    assert result is None


@pytest.mark.asyncio
async def test_get_instance_empty_session_id(mock_redis):
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_instance("agent-1", "")
    assert result is None
    mock_redis.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_instance(mock_redis):
    mgr = SessionManager("redis://localhost")
    await mgr.set_instance("agent-1", "sess-123", "inst-a", ttl=3600)
    mock_redis.set.assert_awaited_once_with("session:agent-1:sess-123", "inst-a", ex=3600)


@pytest.mark.asyncio
async def test_set_instance_empty_session_id(mock_redis):
    mgr = SessionManager("redis://localhost")
    await mgr.set_instance("agent-1", "", "inst-a")
    mock_redis.set.assert_not_awaited()
