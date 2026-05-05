from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from urllib.parse import urlencode

import httpx
import tenacity
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.http_client import get_client_pool, PerAgentClientPool
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.routing import InstanceTarget, RoutingDecisionEngine
from agent_routers.services.session_manager import SessionManager
from agent_routers.errors import AgentNotFoundError, AgentUnavailableError, EndpointNotFoundError

from purgatory.service._async.circuitbreaker import AsyncCircuitBreakerFactory
from purgatory.service._async.unit_of_work import AsyncInMemoryUnitOfWork

logger = logging.getLogger(__name__)

IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}


class _CircuitBreakerWrapper:
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


_cb = _CircuitBreakerWrapper(error_threshold=5, recovery_timeout=60.0)


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


def _extract_value(data: dict, dot_path: str) -> Any:
    if dot_path == "$":
        return data
    current = data
    for part in dot_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _build_url(path_template: str, path_params: dict, query_params: dict) -> str:
    url = path_template.format(**path_params)
    if query_params:
        url = f"{url}?{urlencode(query_params)}"
    return url


def _serialize_body(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, (dict, list, str)):
        return json.dumps(value).encode("utf-8")
    return str(value).encode("utf-8")


class Forwarder:
    def __init__(
        self,
        agent_repo: AgentRepository,
        routing_engine: RoutingDecisionEngine,
        client_pool: PerAgentClientPool,
        session_manager: SessionManager | None = None,
    ):
        self._agent_repo = agent_repo
        self._routing_engine = routing_engine
        self._pool = client_pool
        self._session_manager = session_manager

    async def forward(
        self,
        request: Request,
        agent_id: str,
        endpoint_id: str,
        route_req: RouteRequest,
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

        # Resolve session-based preferred instance
        req_dict = route_req.model_dump()
        session_id = _extract_value(req_dict, "context.session_id")
        preferred_instance = None
        if session_id and self._session_manager:
            preferred_instance = await self._session_manager.get_instance(agent_id, session_id)

        preferred = request.headers.get("X-Preferred-Instance") or preferred_instance
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

        # Build URL from param_mapping
        mapping = endpoint.param_mapping
        path_params = {}
        if mapping:
            for key, dot_path in mapping.get("path_params", {}).items():
                val = _extract_value(req_dict, dot_path)
                if val is not None:
                    path_params[key] = str(val)

        query_params = {}
        if mapping:
            for key, dot_path in mapping.get("query_params", {}).items():
                val = _extract_value(req_dict, dot_path)
                if val is not None:
                    query_params[key] = str(val)

        url = _build_url(endpoint.path, path_params, query_params)

        # Build body
        body_bytes = b""
        if endpoint.method not in IDEMPOTENT_METHODS and mapping and mapping.get("body"):
            body_value = _extract_value(req_dict, mapping["body"])
            body_bytes = _serialize_body(body_value)

        key = _circuit_key(target.agent_id, target.instance_id)
        if await _cb.is_open(key):
            raise AgentUnavailableError(f"Circuit open for {key}")

        if endpoint.mode == "block":
            return await self._forward_block(
                client, endpoint.method, url, dict(request.headers), body_bytes, key,
                endpoint, agent_id, target.instance_id,
            )
        else:
            return await self._forward_stream(
                client, endpoint.method, url, dict(request.headers), body_bytes, cancel_event, key,
                endpoint, agent_id, target.instance_id,
            )

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
        endpoint,
        agent_id: str,
        target_instance_id: str,
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

        # Extract session_id from response
        session_config = endpoint.session_config
        if session_config and self._session_manager:
            session_id = None
            if session_config.get("response_header"):
                session_id = upstream.headers.get(session_config["response_header"])
            if not session_id and session_config.get("response_body_path"):
                content_type = upstream.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        body_json = upstream.json()
                        session_id = _extract_value(body_json, session_config["response_body_path"])
                    except Exception:
                        pass
            if session_id:
                await self._session_manager.set_instance(agent_id, session_id, target_instance_id)

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
        endpoint,
        agent_id: str,
        target_instance_id: str,
    ) -> StreamingResponse:
        async def generator() -> AsyncIterator[bytes]:
            try:
                async with client.stream(method, url, headers=headers, content=body) as upstream:
                    # Extract session_id from stream response header
                    session_config = endpoint.session_config
                    if session_config and session_config.get("response_header") and self._session_manager:
                        session_id = upstream.headers.get(session_config["response_header"])
                        if session_id:
                            await self._session_manager.set_instance(agent_id, session_id, target_instance_id)

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
