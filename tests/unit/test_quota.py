import pytest
import redis.asyncio as redis
from unittest.mock import AsyncMock, MagicMock, patch

from agent_routers.adapters.redis_quota import RedisQuota, QuotaExceeded, QUOTA_LUA


@pytest.fixture
def mock_redis():
    mock = AsyncMock()
    mock.script_load = AsyncMock(return_value="abc123sha")
    mock.evalsha = AsyncMock(return_value=1)
    mock.eval = AsyncMock(return_value=1)
    mock.aclose = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_check_returns_true_when_under_limit(mock_redis):
    with patch("agent_routers.adapters.redis_quota.redis.from_url", return_value=mock_redis):
        quota = RedisQuota("redis://localhost:6379/0", limit=120, window_seconds=60)
        result = await quota.check("user:alice")
        assert result is True
        mock_redis.evalsha.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_raises_quota_exceeded_when_at_limit(mock_redis):
    mock_redis.evalsha = AsyncMock(return_value=-1)
    with patch("agent_routers.adapters.redis_quota.redis.from_url", return_value=mock_redis):
        quota = RedisQuota("redis://localhost:6379/0", limit=120, window_seconds=60)
        with pytest.raises(QuotaExceeded, match="Quota exceeded for user:bob"):
            await quota.check("user:bob")


@pytest.mark.asyncio
async def test_lua_script_fallback_on_noscript(mock_redis):
    """If evalsha fails with NOSCRIPT, fallback to eval and reload script."""
    mock_redis.evalsha = AsyncMock(side_effect=[redis.ResponseError("NOSCRIPT No matching script"), 1])
    with patch("agent_routers.adapters.redis_quota.redis.from_url", return_value=mock_redis):
        quota = RedisQuota("redis://localhost:6379/0", limit=120, window_seconds=60)
        result = await quota.check("user:charlie")
        assert result is True
        assert mock_redis.eval.await_count == 1
        assert mock_redis.script_load.await_count == 2  # initial + fallback reload


@pytest.mark.asyncio
async def test_close_releases_client(mock_redis):
    with patch("agent_routers.adapters.redis_quota.redis.from_url", return_value=mock_redis):
        quota = RedisQuota("redis://localhost:6379/0")
        await quota.check("user:dave")
        assert quota._client is not None
        await quota.close()
        mock_redis.aclose.assert_awaited_once()
        assert quota._client is None


@pytest.mark.asyncio
async def test_ensure_client_loads_script_once(mock_redis):
    with patch("agent_routers.adapters.redis_quota.redis.from_url", return_value=mock_redis):
        quota = RedisQuota("redis://localhost:6379/0")
        await quota.check("user:eve")
        await quota.check("user:eve")
        mock_redis.script_load.assert_awaited_once()
