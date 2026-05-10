from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

CANCEL_CHANNEL = "router:cancel"
CANCEL_KEY_TTL = 30


class CancellationRegistry:
    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def start_tracking(self, request_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self._events[request_id] = event
        return event

    def stop_tracking(self, request_id: str) -> None:
        self._events.pop(request_id, None)

    @asynccontextmanager
    async def track(self, request_id: str) -> AsyncIterator[asyncio.Event]:
        event = self.start_tracking(request_id)
        try:
            yield event
        finally:
            self.stop_tracking(request_id)

    def cancel_local(self, request_id: str) -> bool:
        event = self._events.get(request_id)
        if event is not None:
            event.set()
            logger.info("cancel_local_triggered", extra={"request_id": request_id})
            return True
        return False

    def is_tracked(self, request_id: str) -> bool:
        return request_id in self._events


class CancellationBroadcaster:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._listener_task: asyncio.Task | None = None
        self._running = False

    async def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def publish(self, request_id: str) -> None:
        client = await self._ensure_client()
        try:
            await asyncio.gather(
                client.publish(CANCEL_CHANNEL, request_id),
                client.set(f"cancel:{request_id}", "1", ex=CANCEL_KEY_TTL),
            )
            logger.info("cancel_published", extra={"request_id": request_id})
        except (RedisError, OSError) as e:
            logger.error(
                "cancel_publish_failed",
                extra={"request_id": request_id, "error": str(e)},
            )
            raise

    async def _listen(self, registry: CancellationRegistry) -> None:
        client = await self._ensure_client()
        pubsub = client.pubsub()
        self._pubsub = pubsub
        await pubsub.subscribe(CANCEL_CHANNEL)
        logger.info("cancellation_listener_started")

        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0,
                    )
                    if message is not None and message["type"] == "message":
                        request_id = message["data"]
                        registry.cancel_local(request_id)
                except asyncio.TimeoutError:
                    continue
                except (RedisError, OSError) as e:
                    logger.error("pubsub_listen_error", extra={"error": str(e)})
                    await asyncio.sleep(1)
        finally:
            await pubsub.unsubscribe(CANCEL_CHANNEL)
            await pubsub.aclose()
            logger.info("cancellation_listener_stopped")

    async def start(self, registry: CancellationRegistry) -> None:
        self._running = True
        self._listener_task = asyncio.create_task(self._listen(registry))

    async def stop(self) -> None:
        self._running = False
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def poll_key(self, request_id: str) -> bool:
        try:
            client = await self._ensure_client()
            return await client.exists(f"cancel:{request_id}") == 1
        except (RedisError, OSError) as e:
            logger.warning("cancel_key_poll_failed", extra={"error": str(e)})
            return False


class CancelService:
    def __init__(self, registry: CancellationRegistry, broadcaster: CancellationBroadcaster | None):
        self._registry = registry
        self._broadcaster = broadcaster

    async def cancel(self, request_id: str) -> bool:
        if self._registry.cancel_local(request_id):
            return True
        if self._broadcaster is not None:
            try:
                await self._broadcaster.publish(request_id)
                return True
            except (RedisError, OSError) as e:
                logger.warning(
                    "broadcast_cancel_failed",
                    extra={"request_id": request_id, "error": str(e)},
                )
        return False


_registry: CancellationRegistry | None = None
_broadcaster: CancellationBroadcaster | None = None


def get_registry() -> CancellationRegistry:
    if _registry is None:
        raise RuntimeError("CancellationRegistry not initialized")
    return _registry


def get_broadcaster() -> CancellationBroadcaster | None:
    return _broadcaster


def init_coordination(redis_url: str) -> tuple[CancellationRegistry, CancellationBroadcaster]:
    global _registry, _broadcaster
    _registry = CancellationRegistry()
    _broadcaster = CancellationBroadcaster(redis_url)
    return _registry, _broadcaster
