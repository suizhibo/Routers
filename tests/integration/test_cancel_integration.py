"""End-to-end coordination tests: track → cancel paths across registry,
broadcaster (Pub/Sub mocked), and key fallback (Redis SET key mocked).

These exercise the wiring between components rather than the algorithms
themselves (those are covered in tests/unit/test_coordination.py).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_routers.services.coordination import (
    CANCEL_CHANNEL,
    CancellationBroadcaster,
    CancellationRegistry,
    CancelService,
)


@pytest.mark.asyncio
async def test_local_cancel_short_circuits_broadcast():
    """When the request is tracked locally, CancelService never publishes."""
    registry = CancellationRegistry()
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    svc = CancelService(registry, broadcaster)

    async with registry.track("req-local") as event:
        result = await svc.cancel("req-local")

    assert result is True
    assert event.is_set()
    broadcaster.publish.assert_not_called()


@pytest.mark.asyncio
async def test_listener_relays_pubsub_to_local_registry():
    """Broadcaster's _listen task delivers Pub/Sub messages into the registry."""
    registry = CancellationRegistry()
    broadcaster = CancellationBroadcaster("redis://test/0")

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    delivered = [{"type": "message", "data": "req-remote"}]

    async def get_message_side_effect(*_a, **_kw):
        if delivered:
            return delivered.pop(0)
        broadcaster._running = False
        return None

    mock_pubsub.get_message = AsyncMock(side_effect=get_message_side_effect)
    mock_client = AsyncMock()
    mock_client.pubsub = MagicMock(return_value=mock_pubsub)
    broadcaster._client = mock_client

    async with registry.track("req-remote") as event:
        broadcaster._running = True
        listener = asyncio.create_task(broadcaster._listen(registry))
        await asyncio.wait_for(event.wait(), timeout=2.0)
        await listener

    assert event.is_set()
    mock_pubsub.subscribe.assert_awaited_once_with(CANCEL_CHANNEL)
    mock_pubsub.unsubscribe.assert_awaited_once_with(CANCEL_CHANNEL)


@pytest.mark.asyncio
async def test_publish_writes_pubsub_and_key_fallback():
    """publish() fires Pub/Sub AND SET cancel:{id} so a node that missed the
    broadcast can still pick it up via poll_key on the next chunk."""
    broadcaster = CancellationBroadcaster("redis://test/0")
    mock_client = AsyncMock()
    mock_client.publish = AsyncMock()
    mock_client.set = AsyncMock()
    broadcaster._client = mock_client

    await broadcaster.publish("req-fallback")

    mock_client.publish.assert_awaited_once_with(CANCEL_CHANNEL, "req-fallback")
    mock_client.set.assert_awaited_once_with("cancel:req-fallback", "1", ex=30)


@pytest.mark.asyncio
async def test_poll_key_detects_set_fallback():
    """A node that missed Pub/Sub can still discover the cancel via poll_key."""
    broadcaster = CancellationBroadcaster("redis://test/0")
    mock_client = AsyncMock()
    mock_client.exists = AsyncMock(return_value=1)
    broadcaster._client = mock_client

    found = await broadcaster.poll_key("req-fallback")

    assert found is True
    mock_client.exists.assert_awaited_once_with("cancel:req-fallback")


@pytest.mark.asyncio
async def test_remote_cancel_via_broadcaster_when_not_local():
    """When the request isn't tracked locally, CancelService falls back to publishing."""
    registry = CancellationRegistry()
    broadcaster = MagicMock()
    broadcaster.publish = AsyncMock()
    svc = CancelService(registry, broadcaster)

    result = await svc.cancel("req-on-other-node")

    assert result is True
    broadcaster.publish.assert_awaited_once_with("req-on-other-node")
