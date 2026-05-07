from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from urllib.parse import urlencode

import httpx
import tenacity
from purgatory.service._async.circuitbreaker import AsyncCircuitBreakerFactory
from purgatory.service._async.unit_of_work import AsyncInMemoryUnitOfWork
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.adapters.http_client import PerAgentClientPool
from agent_routers.errors import AgentNotFoundError, AgentUnavailableError, EndpointNotFoundError
from agent_routers.models.agent import Agent, AgentEndpoint
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.routing import RoutingDecisionEngine
from agent_routers.services.session_manager import SessionManager

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


def _circuit_key(agent_id: str, session_id: str) -> str:
    return f"{agent_id}:{session_id}"


def _retry_if_not_cancelled(retry_state: tenacity.RetryCallState) -> bool:
    if retry_state.outcome is None:
        return True
    exc = retry_state.outcome.exception()
    if exc is not None and isinstance(exc, asyncio.CancelledError):
        raise tenacity.RetryError(retry_state)  # type: ignore[arg-type]
    return True


def _is_retryable_http_error(exc: BaseException) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    return 500 <= exc.response.status_code <= 599


def _extract_value(data: dict[str, Any], dot_path: str) -> Any:
    if dot_path == "$":
        return data
    current = data
    for part in dot_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _build_url(
    path_template: str, path_params: dict[str, Any], query_params: dict[str, Any]
) -> str:
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

    @staticmethod
    def _find_endpoint(agent: Agent, endpoint_type: str) -> AgentEndpoint:
        for ep in agent.endpoints:
            if ep.endpoint_type == endpoint_type:
                return ep
        raise EndpointNotFoundError(
            f"Endpoint '{endpoint_type}' not found on agent '{agent.agent_id}'"
        )

    def _build_request(
        self,
        route_req: RouteRequest,
        endpoint: AgentEndpoint,
    ) -> tuple[str, bytes]:
        """Build full URL and body from route request and endpoint mapping."""
        req_dict = route_req.model_dump()
        mapping = endpoint.param_mapping or {}

        path_params = {}
        for key, dot_path in mapping.get("path_params", {}).items():
            val = _extract_value(req_dict, dot_path)
            if val is not None:
                path_params[key] = str(val)

        query_params = {}
        for key, dot_path in mapping.get("query_params", {}).items():
            val = _extract_value(req_dict, dot_path)
            if val is not None:
                query_params[key] = str(val)

        url_path = _build_url(endpoint.path, path_params, query_params)

        body_bytes = b""
        if endpoint.method not in IDEMPOTENT_METHODS and mapping.get("body"):
            body_value = _extract_value(req_dict, mapping["body"])
            body_bytes = _serialize_body(body_value)

        return url_path, body_bytes

    @staticmethod
    def _extract_session_id(upstream: httpx.Response, endpoint: AgentEndpoint) -> str | None:
        """Extract session_id from upstream response using endpoint session config."""
        session_config = endpoint.session_config
        if not session_config:
            return None

        response_header = session_config.get("response_header")
        if response_header:
            session_id = upstream.headers.get(response_header)
            if isinstance(session_id, str):
                return session_id

        response_body_path = session_config.get("response_body_path")
        if response_body_path:
            content_type = upstream.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body_json = upstream.json()
                    result = _extract_value(body_json, response_body_path)
                    if isinstance(result, str):
                        return result
                except (json.JSONDecodeError, ValueError):
                    pass

        return None

    async def _auto_create_session(
        self,
        request: Request,
        route_req: RouteRequest,
        agent_id: str,
    ) -> str:
        create_req = RouteRequest(
            input=route_req.input,
            context={k: v for k, v in route_req.context.items() if k != "session_id"},
            options=route_req.options,
        )

        agent = await self._agent_repo.get_by_id(agent_id)
        if not agent:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")

        endpoint = self._find_endpoint(agent, "create_session")

        url_path, body_bytes = self._build_request(create_req, endpoint)
        base_url = agent.base_url
        full_url = f"{base_url.rstrip('/')}/{url_path.lstrip('/')}"

        client = self._pool.get(agent_id)
        if client is None:
            client = self._pool.create(agent_id, base_url)

        session_headers = dict(request.headers)
        if agent.auth_header and agent.auth_token:
            session_headers[agent.auth_header] = agent.auth_token

        upstream = await client.request(
            endpoint.method, full_url,
            headers=session_headers, content=body_bytes
        )
        upstream.raise_for_status()

        session_id = self._extract_session_id(upstream, endpoint)
        if not session_id:
            raise AgentUnavailableError("Failed to extract session_id from create-session response")

        if self._session_manager:
            await self._session_manager.set_route(session_id, agent_id)

        return session_id

    async def forward(
        self,
        request: Request,
        route_req: RouteRequest,
        cancel_event: asyncio.Event | None,
    ) -> Response:
        session_id = route_req.context.get("session_id")

        # Resolve agent once; session communication always uses "chat" endpoint
        agent_id = await self._routing_engine.resolve(
            route_req, dict(request.headers)
        )

        if not session_id:
            session_id = await self._auto_create_session(request, route_req, agent_id)
            route_req.context["session_id"] = session_id

        # Fetch agent and its chat endpoint
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not registered")

        endpoint = self._find_endpoint(agent, "chat")

        # Build request
        url_path, body_bytes = self._build_request(route_req, endpoint)
        base_url = agent.base_url
        full_url = f"{base_url.rstrip('/')}/{url_path.lstrip('/')}"

        upstream_headers = dict(request.headers)
        if agent.auth_header and agent.auth_token:
            upstream_headers[agent.auth_header] = agent.auth_token

        # 4. Circuit breaker
        circuit_key = _circuit_key(agent_id, session_id)
        if await _cb.is_open(circuit_key):
            raise AgentUnavailableError(f"Circuit open for {circuit_key}")

        client = self._pool.get(agent_id)
        if client is None:
            client = self._pool.create(agent_id, base_url)

        if endpoint.mode == "block":
            return await self._forward_block(
                client, endpoint.method, full_url, upstream_headers, body_bytes,
                circuit_key,
            )
        else:
            return await self._forward_stream(
                client, endpoint.method, full_url, upstream_headers, body_bytes,
                cancel_event, agent_id, session_id,
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
        headers: dict[str, Any],
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
        headers: dict[str, Any],
        body: bytes,
        cancel_event: asyncio.Event | None,
        agent_id: str,
        session_id: str | None,
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
            headers={
                "X-Preferred-Agent": agent_id,
                "X-Session-Id": session_id or "",
            },
        )
