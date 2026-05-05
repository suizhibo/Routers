from __future__ import annotations

import pytest

from agent_routers.adapters.http_client import PerAgentClientPool, get_client_pool


@pytest.fixture
def pool():
    return PerAgentClientPool()


def test_create_and_get(pool):
    client = pool.create("agent-1", "http://localhost:8001")
    assert client is not None
    assert pool.get("agent-1") is client


def test_create_duplicate_raises(pool):
    pool.create("agent-1", "http://localhost:8001")
    with pytest.raises(ValueError, match="already exists"):
        pool.create("agent-1", "http://localhost:8002")


def test_get_missing_returns_none(pool):
    assert pool.get("nonexistent") is None


def test_destroy_removes_client(pool):
    pool.create("agent-1", "http://localhost:8001")
    pool.destroy("agent-1")
    assert pool.get("agent-1") is None


def test_destroy_missing_is_noop(pool):
    pool.destroy("nonexistent")  # should not raise


@pytest.mark.asyncio
async def test_close_all_closes_clients(pool):
    client1 = pool.create("agent-1", "http://localhost:8001")
    client2 = pool.create("agent-2", "http://localhost:8002")

    await pool.close_all()

    assert pool.get("agent-1") is None
    assert pool.get("agent-2") is None
    assert client1.is_closed
    assert client2.is_closed


def test_get_client_pool_singleton():
    p1 = get_client_pool()
    p2 = get_client_pool()
    assert p1 is p2
