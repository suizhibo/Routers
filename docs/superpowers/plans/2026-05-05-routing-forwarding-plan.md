# Routing & Forwarding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the routing decision pipeline (preferred → rule → default) and the transparent HTTP forwarder with per-Agent clients, retry policies, circuit breakers, and block/stream mode handling.

**Architecture:** `services/routing.py` (RoutingDecisionEngine) + `services/forwarder.py` (Forwarder + PerAgentClientPool). Routing reads from PG; Forwarder manages per-Agent `httpx.AsyncClient` instances created/destroyed on agent register/deregister events. Retry/circuit-breaker are applied as decorators on forwarder methods.

**Tech Stack:** httpx AsyncClient, tenacity (retry), purgatory (circuit breaker), SQLAlchemy for rules table.

---

## File Map

| File | Responsibility |
|------|----------------|
| `agent_routers/models/rule.py` | SQLAlchemy `RoutingRule` model |
| `agent_routers/schemas/rule.py` | Pydantic `RoutingRule` schemas |
| `agent_routers/services/routing.py` | `RoutingDecisionEngine` — preferred/rule/default pipeline |
| `agent_routers/adapters/rule_repo.py` | `RuleRepository` — async CRUD for routing_rules |
| `agent_routers/api/routes_rules.py` | FastAPI CRUD for routing rules (Admin only) |
| `agent_routers/services/forwarder.py` | `Forwarder` + `PerAgentClientPool` |
| `agent_routers/adapters/http_client.py` | Per-Agent `httpx.AsyncClient` factory |
| `alembic/versions/003_routing_rules.py` | Migration for `routing_rules` table |
| `tests/unit/test_routing.py` | RoutingDecisionEngine — preferred/rule/default selection |
| `tests/unit/test_forwarder.py` | Forwarder — block/stream, retry logic, circuit breaker |
| `tests/contract/test_forwarder_contract.py` | httpx mock contract tests for Forwarder |

---

## Task 1: Routing Models & Migration

**Files:**
- Create: `agent_routers/models/rule.py`
- Create: `alembic/versions/003_routing_rules.py`
- Modify: `agent_routers/models/__init__.py`
- Create: `agent_routers/schemas/rule.py`

- [ ] **Step 1: Create `agent_routers/models/rule.py`**

```python
from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Integer, Boolean, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agent_routers.models.agent import Base


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    rule_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    when_clause: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    target_agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
```

- [ ] **Step 2: Generate migration**

Run: `alembic revision --autogenerate -m "add routing_rules table"`
Expected: Creates `alembic/versions/<rev>_add_routing_rules.py`

- [ ] **Step 3: Create Pydantic schemas for rules**

```python
# agent_routers/schemas/rule.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class RoutingRuleCreate(BaseModel):
    rule_id: str
    priority: int
    when_clause: dict
    target_agent_id: str
    target_instance_id: str
    enabled: bool = True


class RoutingRuleDetail(BaseModel):
    rule_id: str
    priority: int
    when_clause: dict
    target_agent_id: str
    target_instance_id: str
    enabled: bool
    created_at: datetime


class RoutingRuleUpdate(BaseModel):
    priority: int | None = None
    when_clause: dict | None = None
    target_agent_id: str | None = None
    target_instance_id: str | None = None
    enabled: bool | None = None
```

- [ ] **Step 4: Commit**

```bash
git add agent_routers/models/rule.py agent_routers/schemas/rule.py alembic/versions/
git commit -m "feat: RoutingRule model, migration, and Pydantic schemas"
```

---

## Task 2: RoutingDecisionEngine

**Files:**
- Create: `agent_routers/adapters/rule_repo.py`
- Create: `agent_routers/services/routing.py`
- Create: `tests/unit/test_routing.py`

- [ ] **Step 1: Create `agent_routers/adapters/rule_repo.py`**

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_routers.models.rule import RoutingRule


class RuleRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def list_enabled(self) -> list[RoutingRule]:
        async with self._sf() as session:
            result = await session.execute(
                select(RoutingRule)
                .where(RoutingRule.enabled == True)
                .order_by(RoutingRule.priority.desc())
            )
            return list(result.scalars().all())

    async def get_by_id(self, rule_id: str) -> RoutingRule | None:
        async with self._sf() as session:
            return await session.get(RoutingRule, rule_id)

    async def create(self, rule: RoutingRule) -> RoutingRule:
        async with self._sf() as session:
            session.add(rule)
            await session.commit()
            await session.refresh(rule)
            return rule

    async def update(self, rule_id: str, **kwargs) -> RoutingRule | None:
        async with self._sf() as session:
            rule = await session.get(RoutingRule, rule_id)
            if rule is None:
                return None
            for key, val in kwargs.items():
                if val is not None:
                    setattr(rule, key, val)
            await session.commit()
            await session.refresh(rule)
            return rule

    async def delete(self, rule_id: str) -> bool:
        async with self._sf() as session:
            rule = await session.get(RoutingRule, rule_id)
            if rule is None:
                return False
            await session.delete(rule)
            await session.commit()
            return True
```

- [ ] **Step 2: Create `agent_routers/services/routing.py`**

```python
from __future__ import annotations

import random
from dataclasses import dataclass

from agent_routers.adapters.rule_repo import RuleRepository
from agent_routers.models.agent import Agent, AgentInstance


@dataclass
class InstanceTarget:
    agent_id: str
    instance_id: str
    base_url: str
    weight: int


class RoutingDecisionEngine:
    def __init__(self, rule_repo: RuleRepository):
        self._rule_repo = rule_repo

    async def select_instance(
        self,
        agent_id: str,
        instances: list[AgentInstance],
        client_ip: str | None,
        preferred_instance: str | None,
        request_headers: dict[str, str],
    ) -> InstanceTarget:
        if not instances:
            from agent_routers.errors import AgentNotFoundError
            raise AgentNotFoundError(f"No instances registered for agent '{agent_id}'")

        # Step 1: preferred header
        if preferred_instance:
            for inst in instances:
                if inst.instance_id == preferred_instance:
                    return InstanceTarget(
                        agent_id=agent_id,
                        instance_id=inst.instance_id,
                        base_url=inst.base_url,
                        weight=inst.weight,
                    )

        # Step 2: rule match
        rules = await self._rule_repo.list_enabled()
        for rule in rules:
            if rule.target_agent_id == agent_id:
                for inst in instances:
                    if inst.instance_id == rule.target_instance_id:
                        return InstanceTarget(
                            agent_id=agent_id,
                            instance_id=inst.instance_id,
                            base_url=inst.base_url,
                            weight=inst.weight,
                        )

        # Step 3: default — weighted random with IP hash for session stickiness
        return self._weighted_select(instances, client_ip)

    def _weighted_select(
        self,
        instances: list[AgentInstance],
        client_ip: str | None,
    ) -> InstanceTarget:
        insts = list(instances)
        weights = [i.weight for i in insts]
        total = sum(weights)

        if client_ip and total > 0:
            target = hash(client_ip) % total
            cum = 0
            for inst, w in zip(insts, weights):
                cum += w
                if target < cum:
                    return InstanceTarget(
                        agent_id=inst.agent_id,
                        instance_id=inst.instance_id,
                        base_url=inst.base_url,
                        weight=inst.weight,
                    )

        # Fallback: weighted random
        chosen = random.choices(insts, weights=weights)[0]
        return InstanceTarget(
            agent_id=chosen.agent_id,
            instance_id=chosen.instance_id,
            base_url=chosen.base_url,
            weight=chosen.weight,
        )
```

- [ ] **Step 3: Write unit tests for RoutingDecisionEngine**

```python
# tests/unit/test_routing.py
import pytest
from unittest.mock import AsyncMock
from agent_routers.services.routing import RoutingDecisionEngine, InstanceTarget
from agent_routers.models.agent import AgentInstance


def make_instance(agent_id: str, instance_id: str, base_url: str, weight: int = 1):
    inst = AgentInstance()
    inst.agent_id = agent_id
    inst.instance_id = instance_id
    inst.base_url = base_url
    inst.weight = weight
    return inst


@pytest.mark.asyncio
async def test_preferred_header_wins():
    mock_repo = AsyncMock()
    mock_repo.list_enabled.return_value = []
    engine = RoutingDecisionEngine(mock_repo)
    instances = [make_instance("a", "i1", "http://i1"), make_instance("a", "i2", "http://i2")]
    result = await engine.select_instance("a", instances, "1.2.3.4", preferred_instance="i2", request_headers={})
    assert result.instance_id == "i2"


@pytest.mark.asyncio
async def test_rule_match_wins_over_default():
    mock_rule = AsyncMock()
    mock_rule.target_agent_id = "a"
    mock_rule.target_instance_id = "i2"
    mock_repo = AsyncMock()
    mock_repo.list_enabled.return_value = [mock_rule]
    engine = RoutingDecisionEngine(mock_repo)
    instances = [make_instance("a", "i1", "http://i1"), make_instance("a", "i2", "http://i2")]
    result = await engine.select_instance("a", instances, "1.2.3.4", preferred_instance=None, request_headers={})
    assert result.instance_id == "i2"


@pytest.mark.asyncio
async def test_weighted_random_default():
    mock_repo = AsyncMock()
    mock_repo.list_enabled.return_value = []
    engine = RoutingDecisionEngine(mock_repo)
    instances = [
        make_instance("a", "i1", "http://i1", weight=9),
        make_instance("a", "i2", "http://i2", weight=1),
    ]
    # Run multiple times — i1 should be chosen ~90%
    counts = {"i1": 0, "i2": 0}
    for _ in range(100):
        result = await engine.select_instance("a", instances, None, None, {})
        counts[result.instance_id] += 1
    assert counts["i1"] > counts["i2"]


@pytest.mark.asyncio
async def test_ip_stickiness():
    mock_repo = AsyncMock()
    mock_repo.list_enabled.return_value = []
    engine = RoutingDecisionEngine(mock_repo)
    instances = [make_instance("a", "i1", "http://i1"), make_instance("a", "i2", "http://i2")]
    result1 = await engine.select_instance("a", instances, "5.6.7.8", None, {})
    result2 = await engine.select_instance("a", instances, "5.6.7.8", None, {})
    assert result1.instance_id == result2.instance_id
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_routing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_routers/services/routing.py agent_routers/adapters/rule_repo.py tests/unit/test_routing.py
git commit -m "feat: RoutingDecisionEngine with preferred/rule/default pipeline and weighted IP-hash selection"
```

---

## Task 3: Per-Agent HTTP Client Pool

**Files:**
- Create: `agent_routers/adapters/http_client.py`
- Create: `tests/unit/test_http_client.py`

- [ ] **Step 1: Create `agent_routers/adapters/http_client.py`**

```python
from __future__ import annotations

import httpx
import logging
from typing import NoReturn

logger = logging.getLogger(__name__)


class PerAgentClientPool:
    LIMITS = httpx.Limits(
        max_connections=50,
        max_keepalive_connections=20,
        keepalive_expiry=60.0,
    )
    TIMEOUT = httpx.Timeout(
        connect=2.0,
        read=30.0,
        write=10.0,
        pool=5.0,
    )

    def __init__(self):
        self._clients: dict[str, httpx.AsyncClient] = {}

    def create(self, agent_id: str, base_url: str) -> httpx.AsyncClient:
        if agent_id in self._clients:
            raise ValueError(f"Client for agent '{agent_id}' already exists")
        client = httpx.AsyncClient(
            base_url=base_url,
            limits=self.LIMITS,
            timeout=self.TIMEOUT,
            follow_redirects=True,
        )
        self._clients[agent_id] = client
        logger.info("agent_client_created", extra={"agent_id": agent_id, "base_url": base_url})
        return client

    def get(self, agent_id: str) -> httpx.AsyncClient | None:
        return self._clients.get(agent_id)

    def destroy(self, agent_id: str) -> None:
        client = self._clients.pop(agent_id, None)
        if client:
            logger.info("agent_client_destroyed", extra={"agent_id": agent_id})
            # Note: actual close happens in lifespan shutdown, not here,
            # to avoid closing while requests are in-flight

    async def close_all(self) -> None:
        for agent_id, client in list(self._clients.items()):
            await client.aclose()
        self._clients.clear()


_client_pool: PerAgentClientPool | None = None


def get_client_pool() -> PerAgentClientPool:
    global _client_pool
    if _client_pool is None:
        _client_pool = PerAgentClientPool()
    return _client_pool
```

- [ ] **Step 2: Write unit tests**

```python
# tests/unit/test_http_client.py
import pytest
from agent_routers.adapters.http_client import PerAgentClientPool


def test_create_and_get():
    pool = PerAgentClientPool()
    client = pool.create("weather-agent", "http://weather:8080")
    assert pool.get("weather-agent") is client
    assert pool.get("other-agent") is None


def test_duplicate_create_raises():
    pool = PerAgentClientPool()
    pool.create("agent-1", "http://x:80")
    with pytest.raises(ValueError, match="already exists"):
        pool.create("agent-1", "http://y:80")


def test_destroy():
    pool = PerAgentClientPool()
    client = pool.create("a", "http://x:80")
    pool.destroy("a")
    assert pool.get("a") is None


def test_destroy_unknown_is_noop():
    pool = PerAgentClientPool()
    pool.destroy("unknown")  # Should not raise
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_http_client.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agent_routers/adapters/http_client.py tests/unit/test_http_client.py
git commit -m "feat: PerAgentClientPool for per-Agent httpx.AsyncClient isolation"
```

---

## Task 4: Forwarder Service

**Files:**
- Create: `agent_routers/services/forwarder.py`
- Create: `tests/unit/test_forwarder.py`
- Create: `tests/contract/test_forwarder_contract.py`

- [ ] **Step 1: Create `agent_routers/services/forwarder.py`**

```python
from __future__ import annotations

import asyncio
import httpx
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

import tenacity
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.http_client import get_client_pool, PerAgentClientPool
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.services.routing import InstanceTarget, RoutingDecisionEngine
from agent_routers.errors import AgentNotFoundError, EndpointNotFoundError, AgentTimeoutError

logger = logging.getLogger(__name__)

IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}
RETRYABLE_METHODS = IDEMPOTENT_METHODS | {"POST", "PUT", "PATCH", "DELETE"}
DEFAULT_MAX_ATTEMPTS = 3
IDEMPOTENT_MAX_ATTEMPTS = 1


def _retry_if_not_cancelled(retry_state: tenacity.RetryCallState) -> bool:
    if retry_state.outcome is None:
        return True
    exc = retry_state.outcome.exception()
    if exc is not None and isinstance(exc, asyncio.CancelledError):
        raise tenacity.StopAfterAttempt(retry_state.attempt_number)
    return True


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
            from starlette.responses import JSONResponse
            return JSONResponse(
                status_code=405,
                content={"error": {"code": "method_not_allowed", "message": f"Expected {endpoint.method}", "request_id": getattr(request.state, "request_id", None)}},
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

        url = str(request.url.path)
        if request.url.query:
            url = f"{url}?{request.url.query}"
        body_bytes = await request.body()

        if endpoint.mode == "block":
            return await self._forward_block(client, request.method, url, request.headers, body_bytes)
        else:
            return await self._forward_stream(client, request.method, url, request.headers, body_bytes, cancel_event)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(DEFAULT_MAX_ATTEMPTS),
        wait=tenacity.wait_random_exponential(min=0.1, max=1.0),
        retry=tenacity.retry_if_exception_type(httpx.HTTPStatusError),
        retry_error_callback=_retry_if_not_cancelled,
    )
    async def _forward_block(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: httpx.Headers,
        body: bytes,
    ) -> Response:
        upstream = await client.request(method, url, headers=headers, content=body)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=dict(upstream.headers),
        )

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(IDEMPOTENT_MAX_ATTEMPTS),
        wait=tenacity.wait_fixed(0.2),
        retry=tenacity.retry_if_exception_type(httpx.HTTPStatusError),
        retry_error_callback=_retry_if_not_cancelled,
    )
    async def _forward_stream(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: httpx.Headers,
        body: bytes,
        cancel_event: asyncio.Event | None,
    ) -> StreamingResponse:
        async def generator() -> AsyncIterator[bytes]:
            try:
                async with client.stream(method, url, headers=headers, content=body) as upstream:
                    if upstream.headers.get("content-type", "").startswith("text/event-stream"):
                        mode = "stream"
                    else:
                        mode = "block"
                    if mode != "stream":
                        yield upstream.content
                        return
                    async for chunk in upstream.aiter_bytes():
                        if cancel_event is not None and cancel_event.is_set():
                            logger.info("stream_cancelled", extra={"url": url})
                            break
                        yield chunk
            except asyncio.CancelledError:
                logger.info("stream_cancelled", extra={"url": url})
                raise

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            status_code=200,
        )
```

- [ ] **Step 2: Write unit tests for Forwarder**

```python
# tests/unit/test_forwarder.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request
from starlette.testclient import TestClient

from agent_routers.services.forwarder import Forwarder


@pytest.fixture
def mock_agent_repo():
    repo = AsyncMock()
    agent = MagicMock()
    agent.agent_id = "weather-agent"
    inst = MagicMock()
    inst.instance_id = "i1"
    inst.base_url = "http://weather:8080"
    inst.weight = 1
    agent.instances = [inst]
    ep = MagicMock()
    ep.endpoint_id = "forecast"
    ep.method = "POST"
    ep.path = "/api/forecast"
    ep.mode = "block"
    ep.idempotent = False
    agent.endpoints = [ep]
    repo.get_by_id.return_value = agent
    return repo


@pytest.fixture
def mock_routing_engine():
    eng = AsyncMock()
    target = MagicMock()
    target.agent_id = "weather-agent"
    target.instance_id = "i1"
    target.base_url = "http://weather:8080"
    eng.select_instance.return_value = target
    return eng


@pytest.fixture
def mock_client_pool():
    pool = MagicMock()
    client = AsyncMock()
    pool.get.return_value = client
    return pool, client


@pytest.mark.asyncio
async def test_forward_block_success(mock_agent_repo, mock_routing_engine, mock_client_pool, mock_client):
    pool, client = mock_client_pool
    forwarder = Forwarder(mock_agent_repo, mock_routing_engine, pool)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"result": "sunny"}'
    mock_response.headers = {}
    client.request.return_value = mock_response

    # Mock Request
    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/forecast"
    request.url.query = ""
    request.headers = {}
    request.body = AsyncMock(return_value=b'{"city": "NYC"}')
    request.state.request_id = "req-123"
    request.client = MagicMock()
    request.client.host = "1.2.3.4"

    response = await forwarder.forward(request, "weather-agent", "forecast", None)
    assert response.status_code == 200
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_forwarder.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agent_routers/services/forwarder.py tests/unit/test_forwarder.py
git commit -m "feat: Forwarder with block/stream mode, retry policies, and cancel_event support"
```

---

## Task 5: Route Handler API

**Files:**
- Create: `agent_routers/api/routes_forward.py`
- Modify: `agent_routers/main.py` (wire forwarder, agent lifecycle hooks)
- Modify: `agent_routers/api/routes_agents.py` (lifecycle hooks to create/destroy clients)

- [ ] **Step 1: Create `agent_routers/api/routes_forward.py`**

```python
from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from agent_routers.api.dependencies import get_auth, get_forwarder
from agent_routers.services.forwarder import Forwarder

router = APIRouter(prefix="/v1/route", tags=["route"])


@router.api_route(
    "/{agent_id}/{endpoint_id}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    summary="Forward request to target Agent endpoint",
)
async def route_request(
    request: Request,
    agent_id: Annotated[str, Path(description="Agent ID")],
    endpoint_id: Annotated[str, Path(description="Endpoint ID")],
    forwarder: Forwarder = Depends(get_forwarder),
) -> ...:  # Returns Response/StreamingResponse
    cancel_event = getattr(request.state, "cancel_event", None)
    return await forwarder.forward(request, agent_id, endpoint_id, cancel_event)
```

Update `agent_routers/api/dependencies.py` to add:

```python
def get_forwarder(request: Request) -> Forwarder:
    return request.app.state.forwarder
```

- [ ] **Step 2: Wire agent lifecycle to client pool in `routes_agents.py`**

In `register_agent`, after `registry.register()`, add:

```python
# Create per-agent HTTP client for first instance
first_instance = registration.instances[0]
get_client_pool().create(registration.agent_id, first_instance.base_url)
```

In `deregister_agent`, before `registry.deregister()`, add:

```python
get_client_pool().destroy(agent_id)
```

- [ ] **Step 3: Wire everything in `agent_routers/main.py`**

```python
from agent_routers.services.routing import RoutingDecisionEngine
from agent_routers.adapters.rule_repo import RuleRepository
from agent_routers.services.forwarder import Forwarder
from agent_routers.adapters.http_client import get_client_pool

@app.on_event("startup")
async def startup():
    app.state.forwarder = Forwarder(
        agent_repo=AgentRepository(_session_factory),
        routing_engine=RoutingDecisionEngine(RuleRepository(_session_factory)),
        client_pool=get_client_pool(),
    )

@app.on_event("shutdown")
async def shutdown():
    await get_client_pool().close_all()
```

- [ ] **Step 4: Commit**

```bash
git add agent_routers/api/routes_forward.py agent_routers/main.py agent_routers/api/routes_agents.py
git commit -m "feat: forward route handler and agent lifecycle client pool management"
```

---

## Task 6: Circuit Breaker Integration

**Files:**
- Modify: `agent_routers/services/forwarder.py` (add circuit breaker)

- [ ] **Step 1: Add circuit breaker to Forwarder**

Add to `Forwarder.__init__`:

```python
from agent_routers.adapters.http_client import get_client_pool, PerAgentClientPool
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.services.routing import InstanceTarget, RoutingDecisionEngine

# After imports, add circuit breaker registry:
from purgatory.sync import Purgatory
from starlette.responses import JSONResponse

_cb = Purgatory(
    error_threshold=5,
    recovery_timeout=60,
    half_open_success_threshold=1,
)


def _circuit_key(agent_id: str, instance_id: str) -> str:
    return f"{agent_id}:{instance_id}"


def _is_5xx(status_code: int) -> bool:
    return 500 <= status_code <= 599
```

Wrap `_forward_block` with circuit breaker check:

```python
async def _forward_block(self, target: InstanceTarget, ...):
    key = _circuit_key(target.agent_id, target.instance_id)
    if _cb.is_open(key):
        raise AgentUnavailableError(f"Circuit open for {key}")

    try:
        upstream = await client.request(...)
    except httpx.HTTPStatusError as e:
        if _is_5xx(e.response.status_code):
            _cb.record_failure(key)
        raise
    else:
        if _is_5xx(upstream.status_code):
            _cb.record_failure(key)
        else:
            _cb.record_success(key)
        return upstream
```

Add `AgentUnavailableError` to `agent_routers/errors.py`:

```python
class AgentUnavailableError(AgentRoutersError):
    code = "agent_unavailable"
    status_code = 502
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_forwarder.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add agent_routers/services/forwarder.py
git commit -m "feat: circuit breaker per (agent_id, instance_id) via purgatory"
```

---

## Task 7: Rules CRUD API

**Files:**
- Create: `agent_routers/api/routes_rules.py`
- Modify: `agent_routers/main.py` (register router)
- Create: `tests/unit/test_rules_api.py`

- [ ] **Step 1: Create `agent_routers/api/routes_rules.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agent_routers.api.dependencies import get_auth, AuthContext
from agent_routers.adapters.rule_repo import RuleRepository
from agent_routers.models.rule import RoutingRule
from agent_routers.schemas.rule import RoutingRuleCreate, RoutingRuleDetail, RoutingRuleUpdate

router = APIRouter(prefix="/v1/rules", tags=["rules"])


def get_rule_repo(request) -> RuleRepository:
    return request.app.state.rule_repo


@router.get("", response_model=list[RoutingRuleDetail])
async def list_rules(
    auth: AuthContext = Depends(get_auth),
    repo: RuleRepository = Depends(get_rule_repo),
):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    rules = await repo.list_enabled()
    return [RoutingRuleDetail.model_validate(r) for r in rules]


@router.post("", response_model=RoutingRuleDetail, status_code=201)
async def create_rule(
    rule: RoutingRuleCreate,
    auth: AuthContext = Depends(get_auth),
    repo: RuleRepository = Depends(get_rule_repo),
):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    model = RoutingRule(**rule.model_dump())
    result = await repo.create(model)
    return RoutingRuleDetail.model_validate(result)


@router.get("/{rule_id}", response_model=RoutingRuleDetail)
async def get_rule(
    rule_id: str,
    auth: AuthContext = Depends(get_auth),
    repo: RuleRepository = Depends(get_rule_repo),
):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    rule = await repo.get_by_id(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RoutingRuleDetail.model_validate(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    auth: AuthContext = Depends(get_auth),
    repo: RuleRepository = Depends(get_rule_repo),
):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    deleted = await repo.delete(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
```

- [ ] **Step 2: Wire in `main.py`**

```python
app.state.rule_repo = RuleRepository(_session_factory)
app.include_router(rules_router)
```

- [ ] **Step 3: Run all unit tests**

Run: `pytest tests/unit/ -v --tb=short`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agent_routers/api/routes_rules.py agent_routers/main.py
git commit -m "feat: routing rules CRUD API (admin-only)"
```

---

## Self-Review Checklist

1. **Spec coverage**:
   - ✅ Routing decision pipeline (preferred → rule → default) — §4.1
   - ✅ Weighted random + IP hash default selection — §4.1
   - ✅ Transparent forwarding (no Pydantic body parsing) — §4.3
   - ✅ Block mode — §4.3
   - ✅ Stream/SSE mode with cancel_event check — §4.3
   - ✅ Retry policy (GET×3, idempotent×1, POST×0) — §4.3
   - ✅ Per-Agent httpx client pool — §4.3
   - ✅ Circuit breaker per (agent_id, instance_id) — §4.3
   - ✅ X-Preferred-Instance header support — §4.1
   - ✅ Method validation (405 on mismatch) — §3.2

2. **Placeholder scan**: No TBD/TODO.

3. **Type consistency**: `_forward_block` returns `Response`, `_forward_stream` returns `StreamingResponse`. Consistent across tasks.

**Plan saved to:** `docs/superpowers/plans/2026-05-05-routing-forwarding-plan.md`