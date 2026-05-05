from __future__ import annotations

import asyncio
import httpx
import logging
from typing import AsyncIterator

import tenacity
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.http_client import get_client_pool, PerAgentClientPool
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.services.routing import InstanceTarget, RoutingDecisionEngine
from agent_routers.errors import AgentNotFoundError, AgentUnavailableError, EndpointNotFoundError

from purgatory.service._async.circuitbreaker import AsyncCircuitBreakerFactory
from purgatory.service._async.unit_of_work import AsyncInMemoryUnitOfWork

logger = logging.getLogger(__name__)

IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}


class _CircuitBreakerWrapper:
    """Wraps AsyncCircuitBreakerFactory to provide the is_open/record_failure/record_success API."""

    def __init__(self, error_threshold: int = 5, recovery_timeout: float = 60.0):
        self._uow = AsyncInMemoryUnitOfWork()
        self._factory = AsyncCircuitBreakerFactory(
            default_threshold=error_threshold,
            default_ttl=recovery_timeout,
            uow=self._uow,
        )
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self._factory.initialize()
            self._initialized = True

    async def is_open(self, key: str) -> bool:
        await self._ensure_initialized()
        breaker = await self._factory.get_breaker(key)
        return breaker.context.state == "opened"

    async def record_failure(self, key: str) -> None:
        await self._ensure_initialized()
        breaker = await self._factory.get_breaker(key)
        breaker.context.mark_failure(1)

    async def record_success(self, key: str) -> None:
        await self._ensure_initialized()
        breaker = await self._factory.get_breaker(key)
        breaker.context.recover_failure()


_cb = _CircuitBreakerWrapper(
    error_threshold=5,
    recovery_timeout=60.0,
)


def _circuit_key(agent_id: str, instance_id: str) -> str:
    return f"{agent_id}:{instance_id}"


def _retry_if_not_cancelled(retry_state: tenacity.RetryCallState) -> bool:
    if retry_state.outcome is None:
        return True
    exc = retry_state.outcome.exception()
    if exc is not None and isinstance(exc, asyncio.CancelledError):
        raise tenacity.StopAfterAttempt(retry_state.attempt_number)
    return True


def _is_retryable_http_error(exc: BaseException) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    return 500 <= exc.response.status_code <= 599


class Forwarder:
    def __init__(
        self,
        agent_repo: AgentRepository,
        routing_engine: RoutingDecisionEngine,
        client_pool: PerAgentClientPool,
    ):
        self._agent_repo = agent_repo
        self._routing_engine = routing_engine
        self._pool = client_pool

    async def forward(
        self,
        request: Request,
        agent_id: str,
        endpoint_id: str,
        cancel_event: asyncio.Event | None,
    ) -> Response:
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not registered")

        endpoint = None
        for ep in agent.endpoints:
            if ep.endpoint_id == endpoint_id:
                endpoint = ep
                break
        if endpoint is None:
            raise EndpointNotFoundError(f"Endpoint '{endpoint_id}' not found on agent '{agent_id}'")

        if request.method != endpoint.method:
            return Response(
                content=b'{"error": {"code": "method_not_allowed", "message": "Method mismatch"}}',
                status_code=405,
                media_type="application/json",
            )

        preferred = request.headers.get("X-Preferred-Instance")
        client_ip = request.client.host if request.client else None
        target = await self._routing_engine.select_instance(
            agent_id=agent_id,
            instances=list(agent.instances),
            client_ip=client_ip,
            preferred_instance=preferred,
            request_headers=dict(request.headers),
        )

        client = self._pool.get(agent_id)
        if client is None:
            base_url = next(i.base_url for i in agent.instances if i.instance_id == target.instance_id)
            client = self._pool.create(agent_id, base_url)

        url = endpoint.path
        body_bytes = await request.body()

        key = _circuit_key(target.agent_id, target.instance_id)
        if await _cb.is_open(key):
            raise AgentUnavailableError(f"Circuit open for {key}")

        if endpoint.mode == "block":
            return await self._forward_block(client, request.method, url, request.headers, body_bytes, key)
        else:
            return await self._forward_stream(client, request.method, url, request.headers, body_bytes, cancel_event, key)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_random_exponential(min=0.1, max=1.0),
        retry=tenacity.retry_if_exception(_is_retryable_http_error),
        retry_error_callback=_retry_if_not_cancelled,
    )
    async def _forward_block(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: dict,
        body: bytes,
        circuit_key: str,
    ) -> Response:
        try:
            upstream = await client.request(method, url, headers=headers, content=body)
        except httpx.HTTPStatusError as e:
            if 500 <= e.response.status_code <= 599:
                await _cb.record_failure(circuit_key)
            raise
        else:
            if 500 <= upstream.status_code <= 599:
                await _cb.record_failure(circuit_key)
            else:
                await _cb.record_success(circuit_key)
        upstream.raise_for_status()
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=dict(upstream.headers),
        )

    async def _forward_stream(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: dict,
        body: bytes,
        cancel_event: asyncio.Event | None,
        circuit_key: str,
    ) -> StreamingResponse:
        async def generator() -> AsyncIterator[bytes]:
            try:
                async with client.stream(method, url, headers=headers, content=body) as upstream:
                    async for chunk in upstream.aiter_bytes():
                        if cancel_event is not None and cancel_event.is_set():
                            logger.info("stream_cancelled")
                            break
                        yield chunk
            except asyncio.CancelledError:
                logger.info("stream_cancelled")
                raise

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
        )
