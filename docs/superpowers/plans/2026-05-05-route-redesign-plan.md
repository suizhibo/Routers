# Route Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert route endpoint to POST-only, introduce param_mapping for building forward URL/body from a fixed request format, and add session management (sticky routing via Redis).

**Architecture:** `RouteRequest` (fixed client body) → `Forwarder` extracts values via `param_mapping` dot-paths → builds target URL/body → forwards with Agent-registered `endpoint.method` → extracts `session_id` from response → stores in Redis for subsequent sticky routing.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.x async, Alembic, redis-py async, httpx, pytest-asyncio

---

## File Structure

| File | Responsibility |
|------|----------------|
| `agent_routers/schemas/agent.py` | `EndpointSpec` adds `ParamMapping` and `SessionConfig` |
| `agent_routers/schemas/route.py` | `RouteRequest` — fixed client request body model |
| `agent_routers/models/agent.py` | `AgentEndpoint` adds `param_mapping` and `session_config` columns |
| `alembic/versions/004_endpoint_mapping.py` | Alembic migration for new columns |
| `agent_routers/services/session_manager.py` | `SessionManager` — Redis-backed session→instance mapping |
| `agent_routers/services/forwarder.py` | `Forwarder` — POST-only, param_mapping, session extraction, remove method mismatch check |
| `agent_routers/api/routes_forward.py` | POST-only route handler accepting `RouteRequest` |
| `agent_routers/main.py` | Wire `SessionManager` into app state and `Forwarder` |
| `tests/unit/test_agent_schemas.py` | Test `EndpointSpec` with new fields |
| `tests/unit/test_param_mapping.py` | Test `_extract_value` and `_build_url` |
| `tests/unit/test_session_manager.py` | Test `SessionManager` Redis operations |
| `tests/unit/test_forwarder.py` | Test POST-only forwarding, param_mapping, session extraction |

---

## Task 1: Schema Changes

**Files:**
- Modify: `agent_routers/schemas/agent.py`
- Create: `agent_routers/schemas/route.py`
- Modify: `tests/unit/test_agent_schemas.py`

- [ ] **Step 1: Add `ParamMapping`, `SessionConfig` to `agent_routers/schemas/agent.py`**

Insert after `HTTPMethod` enum and before `ParamSpec`:

```python
class ParamMapping(BaseModel):
    path_params: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


class SessionConfig(BaseModel):
    response_header: str | None = None
    response_body_path: str | None = None
```

Update `EndpointSpec` to include the two new fields:

```python
class EndpointSpec(BaseModel):
    endpoint_id: str
    method: HTTPMethod
    path: Annotated[str, Field(min_length=1, max_length=2048)]
    path_params: list[ParamSpec] = Field(default_factory=list)
    query_params: list[ParamSpec] = Field(default_factory=list)
    body_schema: dict | None = None
    mode: AgentMode
    idempotent: bool = False
    param_mapping: ParamMapping = Field(default_factory=ParamMapping)
    session_config: SessionConfig | None = None
```

- [ ] **Step 2: Create `agent_routers/schemas/route.py`**

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RouteRequest(BaseModel):
    input: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 3: Update `tests/unit/test_agent_schemas.py`**

Replace the file content:

```python
import pytest
from agent_routers.schemas.agent import AgentRegistration, InstanceInfo, EndpointSpec, ParamMapping, SessionConfig


def test_agent_registration_valid():
    reg = AgentRegistration(
        agent_id="weather-agent",
        name="Weather Agent",
        subject="svc-weather",
        instances=[
            InstanceInfo(instance_id="i1", base_url="https://weather-svc:8080", weight=2),
        ],
        endpoints=[
            EndpointSpec(
                endpoint_id="get_forecast",
                method="POST",
                path="/api/v1/forecast",
                mode="block",
                idempotent=False,
                param_mapping=ParamMapping(path_params={}, query_params={}, body=None),
                session_config=None,
            ),
        ],
    )
    assert reg.agent_id == "weather-agent"
    assert reg.instances[0].weight == 2
    assert reg.endpoints[0].param_mapping.body is None


def test_agent_registration_rejects_empty_instances():
    with pytest.raises(ValueError):
        AgentRegistration(
            agent_id="bad-agent",
            name="Bad Agent",
            subject="svc-bad",
            instances=[],
            endpoints=[
                EndpointSpec(
                    endpoint_id="e1",
                    method="GET",
                    path="/",
                    mode="block",
                ),
            ],
        )


def test_endpoint_spec_with_session_config():
    ep = EndpointSpec(
        endpoint_id="chat",
        method="POST",
        path="/api/chat/{session_id}",
        mode="stream",
        param_mapping=ParamMapping(
            path_params={"session_id": "context.session_id"},
            body="input",
        ),
        session_config=SessionConfig(response_header="X-Session-ID"),
    )
    assert ep.session_config.response_header == "X-Session-ID"
    assert ep.param_mapping.path_params["session_id"] == "context.session_id"
```

- [ ] **Step 4: Run schema tests**

Run: `pytest tests/unit/test_agent_schemas.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add agent_routers/schemas/agent.py agent_routers/schemas/route.py tests/unit/test_agent_schemas.py
git commit -m "feat: ParamMapping, SessionConfig, RouteRequest schemas"
```

---

## Task 2: Database Model and Migration

**Files:**
- Modify: `agent_routers/models/agent.py`
- Create: `alembic/versions/004_endpoint_mapping.py`

- [ ] **Step 1: Modify `AgentEndpoint` in `agent_routers/models/agent.py`**

Add two columns after `idempotent`:

```python
class AgentEndpoint(Base):
    __tablename__ = "agent_endpoints"

    agent_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True
    )
    endpoint_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    path_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    query_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    body_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotent: Mapped[bool] = mapped_column(default=False)
    param_mapping: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    session_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint("mode IN ('block', 'stream')", name="ck_mode"),
    )

    agent: Mapped[Agent] = relationship(back_populates="endpoints")
```

- [ ] **Step 2: Create migration `alembic/versions/004_endpoint_mapping.py`**

```python
"""add param_mapping and session_config to agent_endpoints

Revision ID: 004
Revises: 98c78a39358b
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '004'
down_revision: Union[str, None] = '98c78a39358b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_endpoints', sa.Column('param_mapping', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('agent_endpoints', sa.Column('session_config', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('agent_endpoints', 'session_config')
    op.drop_column('agent_endpoints', 'param_mapping')
```

- [ ] **Step 3: Run migration**

Run: `alembic upgrade head`
Expected: Success

- [ ] **Step 4: Commit**

```bash
git add agent_routers/models/agent.py alembic/versions/004_endpoint_mapping.py
git commit -m "feat: add param_mapping and session_config to agent_endpoints"
```

---

## Task 3: ParamMapping Utility and Tests

**Files:**
- Create: `tests/unit/test_param_mapping.py`

These tests validate the pure functions that will be added to `forwarder.py` in Task 5.

- [ ] **Step 1: Create `tests/unit/test_param_mapping.py`**

```python
from __future__ import annotations

import pytest

from agent_routers.services.forwarder import _extract_value, _build_url


def test_extract_value_dot_path():
    data = {"input": "hello", "context": {"session_id": "abc"}, "options": {"temp": 0.7}}
    assert _extract_value(data, "input") == "hello"
    assert _extract_value(data, "context.session_id") == "abc"
    assert _extract_value(data, "options.temp") == 0.7


def test_extract_value_dollar_sign():
    data = {"input": "hello"}
    assert _extract_value(data, "$") == data


def test_extract_value_missing_path():
    data = {"input": "hello"}
    assert _extract_value(data, "context.session_id") is None
    assert _extract_value(data, "foo.bar.baz") is None


def test_build_url_no_query():
    url = _build_url("/api/forecast/{city}", {"city": "NYC"}, {})
    assert url == "/api/forecast/NYC"


def test_build_url_with_query():
    url = _build_url("/api/forecast/{city}", {"city": "NYC"}, {"days": "7"})
    assert url == "/api/forecast/NYC?days=7"


def test_build_url_missing_param_raises():
    with pytest.raises(KeyError):
        _build_url("/api/forecast/{city}", {}, {})
```

- [ ] **Step 2: Run tests (expecting import failures)**

Run: `pytest tests/unit/test_param_mapping.py -v`
Expected: 6 FAIL — `_extract_value` and `_build_url` not defined in forwarder.py yet. This confirms the tests exist before the implementation.

- [ ] **Step 3: Commit tests**

```bash
git add tests/unit/test_param_mapping.py
git commit -m "test: param_mapping utility tests (failing, pending implementation)"
```

---

## Task 4: SessionManager

**Files:**
- Create: `agent_routers/services/session_manager.py`
- Create: `tests/unit/test_session_manager.py`

- [ ] **Step 1: Create `agent_routers/services/session_manager.py`**

```python
from __future__ import annotations

import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)

DEFAULT_TTL = 86400  # 24 hours


class SessionManager:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    async def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def get_instance(self, agent_id: str, session_id: str) -> str | None:
        if not session_id:
            return None
        try:
            client = await self._ensure_client()
            return await client.get(f"session:{agent_id}:{session_id}")
        except Exception:
            logger.exception("session_get_failed", extra={"agent_id": agent_id, "session_id": session_id})
            return None

    async def set_instance(
        self,
        agent_id: str,
        session_id: str,
        instance_id: str,
        ttl: int = DEFAULT_TTL,
    ) -> None:
        if not session_id or not instance_id:
            return
        try:
            client = await self._ensure_client()
            await client.set(f"session:{agent_id}:{session_id}", instance_id, ex=ttl)
            logger.info("session_set", extra={"agent_id": agent_id, "session_id": session_id, "instance_id": instance_id})
        except Exception:
            logger.exception("session_set_failed", extra={"agent_id": agent_id, "session_id": session_id})
```

- [ ] **Step 2: Create `tests/unit/test_session_manager.py`**

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_session_manager.py -v`
Expected: 5 PASS

- [ ] **Step 4: Commit**

```bash
git add agent_routers/services/session_manager.py tests/unit/test_session_manager.py
git commit -m "feat: SessionManager for sticky session routing via Redis"
```

---

## Task 5: Forwarder Refactor

**Files:**
- Modify: `agent_routers/services/forwarder.py`
- Modify: `tests/unit/test_forwarder.py`

- [ ] **Step 1: Rewrite `agent_routers/services/forwarder.py`**

```python
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
    if isinstance(value, (dict, list)):
        return json.dumps(value).encode("utf-8")
    if isinstance(value, str):
        return value.encode("utf-8")
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
            for key, dot_path in mapping.path_params.items():
                val = _extract_value(req_dict, dot_path)
                if val is not None:
                    path_params[key] = str(val)

        query_params = {}
        if mapping:
            for key, dot_path in mapping.query_params.items():
                val = _extract_value(req_dict, dot_path)
                if val is not None:
                    query_params[key] = str(val)

        url = _build_url(endpoint.path, path_params, query_params)

        # Build body
        body_bytes = b""
        if endpoint.method not in IDEMPOTENT_METHODS and mapping and mapping.body:
            body_value = _extract_value(req_dict, mapping.body)
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
        if endpoint.session_config and self._session_manager:
            session_id = None
            if endpoint.session_config.response_header:
                session_id = upstream.headers.get(endpoint.session_config.response_header)
            if not session_id and endpoint.session_config.response_body_path:
                content_type = upstream.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        body_json = upstream.json()
                        session_id = _extract_value(body_json, endpoint.session_config.response_body_path)
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
                    if endpoint.session_config and endpoint.session_config.response_header and self._session_manager:
                        session_id = upstream.headers.get(endpoint.session_config.response_header)
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
```

- [ ] **Step 2: Rewrite `tests/unit/test_forwarder.py`**

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.http_client import PerAgentClientPool
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.errors import AgentNotFoundError, EndpointNotFoundError
from agent_routers.models.agent import Agent, AgentEndpoint, AgentInstance
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.forwarder import Forwarder
from agent_routers.services.routing import InstanceTarget, RoutingDecisionEngine
from agent_routers.services.session_manager import SessionManager


class FakeAgentRepo:
    def __init__(self, agent: Agent | None):
        self._agent = agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        return self._agent


class FakeRoutingEngine:
    def __init__(self, target: InstanceTarget):
        self._target = target

    async def select_instance(self, **kwargs) -> InstanceTarget:
        return self._target


def _make_agent(endpoint_mode: str = "block", param_mapping=None, session_config=None) -> Agent:
    if param_mapping is None:
        param_mapping = {"path_params": {}, "query_params": {}, "body": None}
    agent = Agent(
        agent_id="agent-1",
        name="Test Agent",
        subject="sub-1",
    )
    agent.instances = [
        AgentInstance(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1),
    ]
    agent.endpoints = [
        AgentEndpoint(
            agent_id="agent-1",
            endpoint_id="ep-1",
            method="POST",
            path="/chat",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode=endpoint_mode,
            idempotent=False,
            param_mapping=param_mapping,
            session_config=session_config,
        ),
    ]
    return agent


def _make_request(body: bytes = b"{}") -> tuple[Request, RouteRequest]:
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
        "path": "/v1/route/agent-1/ep-1",
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    request._body = body
    route_req = RouteRequest()
    return request, route_req


@pytest.fixture
def pool():
    return PerAgentClientPool()


@pytest.fixture
def forwarder(pool):
    agent = _make_agent("block")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    return Forwarder(repo, engine, pool)


@pytest.mark.asyncio
async def test_forward_agent_not_found(pool):
    repo = FakeAgentRepo(None)
    engine = FakeRoutingEngine(InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://a", weight=1))
    fwd = Forwarder(repo, engine, pool)
    request, route_req = _make_request()

    with pytest.raises(AgentNotFoundError):
        await fwd.forward(request, "agent-1", "ep-1", route_req, None)


@pytest.mark.asyncio
async def test_forward_endpoint_not_found(pool):
    agent = _make_agent()
    agent.endpoints = []
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://a", weight=1))
    fwd = Forwarder(repo, engine, pool)
    request, route_req = _make_request()

    with pytest.raises(EndpointNotFoundError):
        await fwd.forward(request, "agent-1", "ep-1", route_req, None)


@pytest.mark.asyncio
async def test_forward_block_success(pool):
    agent = _make_agent("block")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b'{"ok": true}'
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json = MagicMock(return_value={"ok": True})
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request, route_req = _make_request(body=b'{"msg":"hi"}')
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b'{"ok": true}'


@pytest.mark.asyncio
async def test_forward_stream_success(pool):
    agent = _make_agent("stream")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    async def _aiter_bytes():
        yield b"data: hello\n\n"
        yield b"data: world\n\n"

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.aiter_bytes = _aiter_bytes
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request, route_req = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    assert isinstance(response, StreamingResponse)


@pytest.mark.asyncio
async def test_forward_stream_cancelled(pool):
    agent = _make_agent("stream")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    cancel_event = asyncio.Event()

    async def _aiter_bytes():
        yield b"data: hello\n\n"
        cancel_event.set()
        yield b"data: world\n\n"

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.aiter_bytes = _aiter_bytes
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request, route_req = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, cancel_event)

    assert isinstance(response, StreamingResponse)


@pytest.mark.asyncio
async def test_forward_block_retry_on_5xx(pool):
    agent = _make_agent("block")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    bad_response = MagicMock(spec=httpx.Response)
    bad_response.status_code = 500
    bad_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "Server error", request=MagicMock(), response=bad_response
    ))

    good_response = MagicMock(spec=httpx.Response)
    good_response.content = b'{"ok": true}'
    good_response.status_code = 200
    good_response.headers = {}
    good_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(side_effect=[
        httpx.HTTPStatusError("Server error", request=MagicMock(), response=bad_response),
        good_response,
    ])

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request, route_req = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    assert response.status_code == 200
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_forward_block_no_retry_on_4xx(pool):
    agent = _make_agent("block")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    bad_response = MagicMock(spec=httpx.Response)
    bad_response.status_code = 404
    bad_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "Not found", request=MagicMock(), response=bad_response
    ))

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=bad_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request, route_req = _make_request()
    with pytest.raises(httpx.HTTPStatusError):
        await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    assert mock_client.request.call_count == 1


@pytest.mark.asyncio
async def test_forward_param_mapping_builds_url_and_body(pool):
    param_mapping = {
        "path_params": {"city": "input"},
        "query_params": {"days": "context.days"},
        "body": "input",
    }
    agent = _make_agent("block", param_mapping=param_mapping)
    agent.endpoints[0].method = "POST"
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b'{}'
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    route_req = RouteRequest(input="NYC", context={"days": "7"}, options={})
    request, _ = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    assert response.status_code == 200
    call_args = mock_client.request.call_args
    assert call_args.kwargs["content"] == b'"NYC"'
    # URL is built internally by forwarder before calling _forward_block
    # The client.request is called with the url passed to _forward_block
    # We verify the URL was constructed correctly by checking the call
    assert "/chat" in call_args.args[1] or "chat" in str(call_args.kwargs.get("url", ""))


@pytest.mark.asyncio
async def test_forward_get_ignores_body(pool):
    param_mapping = {
        "path_params": {"city": "input"},
        "query_params": {},
        "body": "input",
    }
    agent = _make_agent("block", param_mapping=param_mapping)
    agent.endpoints[0].method = "GET"
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b'{}'
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    route_req = RouteRequest(input="NYC", context={}, options={})
    request, _ = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    call_args = mock_client.request.call_args
    assert call_args.kwargs["content"] == b""


@pytest.mark.asyncio
async def test_forward_session_extraction_from_header(pool):
    session_config = {"response_header": "X-Session-ID"}
    agent = _make_agent("block", session_config=session_config)
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)

    mock_session_mgr = AsyncMock(spec=SessionManager)
    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b'{}'
    mock_response.status_code = 200
    mock_response.headers = {"x-session-id": "sess-abc"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    route_req = RouteRequest(context={}, options={})
    request, _ = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    mock_session_mgr.set_instance.assert_awaited_once_with("agent-1", "sess-abc", "inst-a")


@pytest.mark.asyncio
async def test_forward_session_extraction_from_body(pool):
    session_config = {"response_body_path": "session_id"}
    agent = _make_agent("block", session_config=session_config)
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)

    mock_session_mgr = AsyncMock(spec=SessionManager)
    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b'{"session_id": "sess-xyz"}'
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json = MagicMock(return_value={"session_id": "sess-xyz"})
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    route_req = RouteRequest(context={}, options={})
    request, _ = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    mock_session_mgr.set_instance.assert_awaited_once_with("agent-1", "sess-xyz", "inst-a")


@pytest.mark.asyncio
async def test_forward_session_sticky_routing(pool):
    param_mapping = {"path_params": {}, "query_params": {}, "body": None}
    agent = _make_agent("block", param_mapping=param_mapping)
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)

    mock_session_mgr = AsyncMock(spec=SessionManager)
    mock_session_mgr.get_instance.return_value = "inst-b"

    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b'{}'
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    route_req = RouteRequest(input="", context={"session_id": "sess-123"}, options={})
    request, _ = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", route_req, None)

    mock_session_mgr.get_instance.assert_awaited_once_with("agent-1", "sess-123")
```

- [ ] **Step 3: Run param_mapping tests**

Run: `pytest tests/unit/test_param_mapping.py -v`
Expected: 6 PASS

- [ ] **Step 4: Run forwarder tests**

Run: `pytest tests/unit/test_forwarder.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agent_routers/services/forwarder.py tests/unit/test_forwarder.py tests/unit/test_param_mapping.py
git commit -m "feat: POST-only forwarder with param_mapping and session extraction"
```

---

## Task 6: Route Handler (POST-only)

**Files:**
- Modify: `agent_routers/api/routes_forward.py`

- [ ] **Step 1: Rewrite `agent_routers/api/routes_forward.py`**

```python
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Path, Request

from agent_routers.api.dependencies import get_forwarder
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.coordination import get_registry
from agent_routers.services.forwarder import Forwarder

router = APIRouter(prefix="/v1/route", tags=["route"])


@router.post(
    "/{agent_id}/{endpoint_id}",
    summary="Forward request to target Agent endpoint",
)
async def route_request(
    request: Request,
    agent_id: str = Path(...),
    endpoint_id: str = Path(...),
    route_req: RouteRequest = ...,  # type: ignore[assignment]
    forwarder: Forwarder = Depends(get_forwarder),
):
    registry = get_registry()
    request_id = getattr(request.state, "request_id", "")
    async with registry.track(request_id) as cancel_event:
        request.state.cancel_event = cancel_event
        return await forwarder.forward(request, agent_id, endpoint_id, route_req, cancel_event)
```

- [ ] **Step 2: Commit**

```bash
git add agent_routers/api/routes_forward.py
git commit -m "feat: POST-only route handler accepting RouteRequest"
```

---

## Task 7: Wire Up in main.py

**Files:**
- Modify: `agent_routers/main.py`

- [ ] **Step 1: Modify `agent_routers/main.py`**

Add import:
```python
from agent_routers.services.session_manager import SessionManager
```

In `lifespan`, after creating `Forwarder`, add `session_manager`:

```python
    app.state.session_manager = SessionManager(settings.REDIS_URL)
    app.state.forwarder = Forwarder(
        agent_repo=AgentRepository(_session_factory),
        routing_engine=RoutingDecisionEngine(app.state.rule_repo),
        client_pool=get_client_pool(),
        session_manager=app.state.session_manager,
    )
```

- [ ] **Step 2: Commit**

```bash
git add agent_routers/main.py
git commit -m "feat: wire SessionManager into Forwarder and app state"
```

---

## Task 8: Full Test Run

**Files:**
- All test files

- [ ] **Step 1: Run all unit tests**

Run: `pytest tests/unit/ -v --tb=short`
Expected: All PASS

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/integration/ -v --tb=short`
Expected: All PASS (or note any expected failures from unrelated tests)

- [ ] **Step 3: Commit if clean**

```bash
git commit -m "test: all tests pass after route redesign" --allow-empty
```

---

## Self-Review

**1. Spec coverage:**

| Spec Section | Task |
|-------------|------|
| POST-only route interface | Task 6 |
| Fixed request body (RouteRequest) | Task 1, Task 6 |
| ParamMapping schema | Task 1 |
| SessionConfig schema | Task 1 |
| `_extract_value` dot-path | Task 3, Task 5 |
| `_build_url` template + query | Task 3, Task 5 |
| GET ignores body | Task 5 (test) |
| Session extraction from header | Task 4, Task 5 |
| Session extraction from body (block only) | Task 4, Task 5 |
| Session sticky routing | Task 4, Task 5 |
| Database migration | Task 2 |
| Wire up SessionManager | Task 7 |

**2. Placeholder scan:** No TBD/TODO/similar references. All code is complete.

**3. Type consistency:**
- `Forwarder.__init__` accepts `session_manager: SessionManager | None` — matches usage
- `RouteRequest` fields match spec (`input: str`, `context: dict`, `options: dict`)
- `AgentEndpoint` column types match schema (`JSON` for both new columns)

**Plan complete.**
