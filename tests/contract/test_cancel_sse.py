"""Contract test: Forwarder._forward_stream MUST stop yielding chunks
once cancel_event.is_set(), and the StreamingResponse generator must
exit cleanly (no chunks lost, no leaked stream context).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from agent_routers.services.forwarder import Forwarder


def _build_forwarder() -> Forwarder:
    return Forwarder(
        agent_repo=MagicMock(),
        routing_engine=MagicMock(),
        client_pool=MagicMock(),
    )


def _stream_client(chunks: list[bytes], chunk_gate: asyncio.Event | None = None) -> MagicMock:
    """Build a mock httpx.AsyncClient whose .stream() yields the given chunks.

    If chunk_gate is provided, the generator awaits it between every chunk so
    the test can interleave a cancel between yields.
    """
    upstream = MagicMock()

    async def aiter_bytes():
        for chunk in chunks:
            if chunk_gate is not None:
                await chunk_gate.wait()
                chunk_gate.clear()
            yield chunk

    upstream.aiter_bytes = aiter_bytes

    @asynccontextmanager
    async def stream_cm(*_a, **_kw):
        yield upstream

    client = MagicMock(spec=httpx.AsyncClient)
    client.stream = stream_cm
    return client


@pytest.mark.asyncio
async def test_stream_yields_all_chunks_when_no_cancel():
    forwarder = _build_forwarder()
    client = _stream_client([b"a", b"b", b"c"])
    cancel_event = asyncio.Event()

    response = await forwarder._forward_stream(
        client=client,
        method="POST",
        url="/stream",
        headers={},
        body=b"",
        cancel_event=cancel_event,
        circuit_key="agent:i1",
    )

    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks == [b"a", b"b", b"c"]
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_stream_breaks_when_cancel_event_set_mid_stream():
    """Set cancel after yielding the first chunk; the generator should not
    deliver any further chunks even though the upstream still has them."""
    forwarder = _build_forwarder()
    gate = asyncio.Event()
    gate.set()  # let the first chunk through immediately
    client = _stream_client([b"first", b"second", b"third"], chunk_gate=gate)
    cancel_event = asyncio.Event()

    response = await forwarder._forward_stream(
        client=client,
        method="POST",
        url="/stream",
        headers={},
        body=b"",
        cancel_event=cancel_event,
        circuit_key="agent:i1",
    )

    received: list[bytes] = []
    iterator = response.body_iterator
    received.append(await iterator.__anext__())

    cancel_event.set()
    gate.set()  # release the next chunk so the loop reaches its is_set check

    with pytest.raises(StopAsyncIteration):
        await iterator.__anext__()

    assert received == [b"first"]


@pytest.mark.asyncio
async def test_stream_handles_no_cancel_event_argument():
    """When cancel_event is None (cancellation disabled), all chunks flow."""
    forwarder = _build_forwarder()
    client = _stream_client([b"x", b"y"])

    response = await forwarder._forward_stream(
        client=client,
        method="GET",
        url="/feed",
        headers={},
        body=b"",
        cancel_event=None,
        circuit_key="agent:i1",
    )

    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks == [b"x", b"y"]


@pytest.mark.asyncio
async def test_stream_propagates_cancelled_error():
    """If the body iterator is cancelled at the asyncio level, the generator
    re-raises CancelledError so the caller sees the cancellation cleanly."""
    forwarder = _build_forwarder()

    @asynccontextmanager
    async def stream_cm(*_a, **_kw):
        upstream = MagicMock()

        async def aiter_bytes():
            yield b"only"
            await asyncio.sleep(60)  # long enough to be cancelled

        upstream.aiter_bytes = aiter_bytes
        yield upstream

    client = MagicMock(spec=httpx.AsyncClient)
    client.stream = stream_cm

    response = await forwarder._forward_stream(
        client=client,
        method="GET",
        url="/feed",
        headers={},
        body=b"",
        cancel_event=None,
        circuit_key="agent:i1",
    )

    iterator = response.body_iterator
    assert await iterator.__anext__() == b"only"

    consumer = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
