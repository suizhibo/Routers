from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_routers.services.coordination import (
    CancellationRegistry,
    CancellationBroadcaster,
    CancelService,
    CANCEL_CHANNEL,
)


class TestCancellationRegistry:
    @pytest.mark.asyncio
    async def test_track_yields_event(self):
        registry = CancellationRegistry()
        async with registry.track("req-1") as event:
            assert isinstance(event, asyncio.Event)
            assert registry.is_tracked("req-1")
        assert not registry.is_tracked("req-1")

    @pytest.mark.asyncio
    async def test_cancel_local_sets_event(self):
        registry = CancellationRegistry()
        async with registry.track("req-2") as event:
            assert not event.is_set()
            result = registry.cancel_local("req-2")
            assert result is True
            assert event.is_set()

    def test_cancel_local_unknown_returns_false(self):
        registry = CancellationRegistry()
        result = registry.cancel_local("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_track_cleanup_on_exception(self):
        registry = CancellationRegistry()
        with pytest.raises(ValueError):
            async with registry.track("req-3"):
                raise ValueError("boom")
        assert not registry.is_tracked("req-3")


class TestCancellationBroadcaster:
    @pytest.fixture
    def broadcaster(self):
        return CancellationBroadcaster("redis://localhost:6379/0")

    @pytest.mark.asyncio
    async def test_publish(self, broadcaster):
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock()
        mock_client.set = AsyncMock()
        broadcaster._client = mock_client

        await broadcaster.publish("req-4")

        mock_client.publish.assert_awaited_once_with(CANCEL_CHANNEL, "req-4")
        mock_client.set.assert_awaited_once_with("cancel:req-4", "1", ex=30)

    @pytest.mark.asyncio
    async def test_publish_raises_on_error(self, broadcaster):
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(side_effect=ConnectionError("redis down"))
        broadcaster._client = mock_client

        with pytest.raises(ConnectionError):
            await broadcaster.publish("req-5")

    @pytest.mark.asyncio
    async def test_listen_forwards_to_registry(self, broadcaster):
        registry = CancellationRegistry()
        mock_client = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        messages = [
            {"type": "message", "data": "req-6"},
            None,  # timeout
        ]

        async def get_message_side_effect(*args, **kwargs):
            if messages:
                return messages.pop(0)
            broadcaster._running = False
            return None

        mock_pubsub.get_message = AsyncMock(side_effect=get_message_side_effect)
        mock_client.pubsub = MagicMock(return_value=mock_pubsub)
        broadcaster._client = mock_client
        broadcaster._running = True

        await broadcaster._listen(registry)

        assert registry.is_tracked("req-6") is False  # event was set and popped

    @pytest.mark.asyncio
    async def test_start_and_stop(self, broadcaster):
        registry = CancellationRegistry()
        mock_client = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        call_count = 0

        async def get_message_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                broadcaster._running = False
            raise asyncio.TimeoutError

        mock_pubsub.get_message = AsyncMock(side_effect=get_message_side_effect)
        mock_client.pubsub = MagicMock(return_value=mock_pubsub)
        broadcaster._client = mock_client

        await broadcaster.start(registry)
        assert broadcaster._running is True
        assert broadcaster._listener_task is not None

        # Wait for the listener to exit its loop
        await broadcaster._listener_task

        await broadcaster.stop()
        assert broadcaster._running is False
        assert broadcaster._listener_task is None

    @pytest.mark.asyncio
    async def test_poll_key(self, broadcaster):
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(return_value=1)
        broadcaster._client = mock_client

        result = await broadcaster.poll_key("req-7")
        assert result is True
        mock_client.exists.assert_awaited_once_with("cancel:req-7")

    @pytest.mark.asyncio
    async def test_poll_key_returns_false_on_error(self, broadcaster):
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(side_effect=ConnectionError("redis down"))
        broadcaster._client = mock_client

        result = await broadcaster.poll_key("req-8")
        assert result is False


class TestCancelService:
    @pytest.mark.asyncio
    async def test_cancel_local(self):
        registry = CancellationRegistry()
        svc = CancelService(registry, None)
        async with registry.track("req-9") as event:
            result = await svc.cancel("req-9")
            assert result is True
            assert event.is_set()

    @pytest.mark.asyncio
    async def test_cancel_broadcasts_when_not_local(self):
        registry = CancellationRegistry()
        broadcaster = MagicMock()
        broadcaster.publish = AsyncMock()
        svc = CancelService(registry, broadcaster)

        result = await svc.cancel("req-10")
        assert result is True
        broadcaster.publish.assert_awaited_once_with("req-10")

    @pytest.mark.asyncio
    async def test_cancel_returns_false_when_no_broadcaster(self):
        registry = CancellationRegistry()
        svc = CancelService(registry, None)
        result = await svc.cancel("req-11")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_broadcast_failure_returns_false(self):
        registry = CancellationRegistry()
        broadcaster = MagicMock()
        broadcaster.publish = AsyncMock(side_effect=ConnectionError("redis down"))
        svc = CancelService(registry, broadcaster)

        result = await svc.cancel("req-12")
        assert result is False
