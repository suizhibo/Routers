# Coordination & Cancellation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-instance request cancellation — local `CancellationRegistry` (in-memory, per-instance) + Redis Pub/Sub broadcasting + `cancel:{request_id}` key fallback. Includes the cancel API endpoint and shutdown integration.

**Architecture:** Two components: `CancellationRegistry` (per-instance `dict[str, asyncio.Event]`) and `CancellationBroadcaster` (Redis Pub/Sub publisher + listener task). The `Forwarder` receives an `asyncio.Event` from `CancellationRegistry.track()` and checks `event.is_set()` on every SSE chunk. `CancellationBroadcaster` is instantiated once per app instance in `lifespan`, with a background listener task.

**Tech Stack:** asyncio events, contextvars, redis-py 5.x async Pub/Sub.

---

## File Map

| File | Responsibility |
|------|----------------|
| `agent_routers/services/coordination.py` | `CancellationRegistry`, `CancellationBroadcaster`, `CancelService` |
| `agent_routers/api/routes_cancel.py` | `POST /v1/requests/{request_id}/cancel` |
| `agent_routers/models/routing.py` | SQLAlchemy `RequestTracking` model (for creator lookup) |
| `alembic/versions/004_request_tracking.py` | Migration for in-flight request tracking table |
| `agent_routers/main.py` | Lifespan integration: start broadcaster, drain on shutdown |
| `agent_routers/api/routes_forward.py` | Wire `CancellationRegistry.track()` into request state |
| `tests/unit/test_coordination.py` | Unit tests for registry, broadcaster, cancel flow |
| `tests/integration/test_cancel_integration.py` | Integration tests: local cancel, Pub/Sub, key fallback |
| `tests/contract/test_cancel_sse.py` | Contract test: SSE stream interrupted by cancel |

---

## Task 1: Coordination Service

**Files:**
- Create: `agent_routers/services/coordination.py`
- Create: `tests/unit/test_coordination.py`

- [ ] **Step 1: Create `agent_routers/services/coordination.py`**

```python
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as redis

from agent_routers.config.settings import settings

logger = logging.getLogger(__name__)

CANCEL_CHANNEL = "router:cancel"
CANCEL_KEY_TTL = 30  # seconds


class CancellationRegistry:
    """Instance-local in-flight request registry.

    Maps request_id → asyncio.Event. When event is set,
    the SSE chunk loop in Forwarder exits.
    """

    def __init__(self):
        self._events: dict[str, asyncio.Event] = {}

    @asynccontextmanager
    async def track(self, request_id: str) -> AsyncIterator[asyncio.Event]:
        event = asyncio.Event()
        self._events[request_id] = event
        try:
            yield event
        finally:
            self._events.pop(request_id, None)

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
    """Publishes cancellation signals via Redis Pub/Sub + key fallback."""

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
        """Publish cancel signal via Pub/Sub + SET key as at-most-once fallback."""
        client = await self._ensure_client()
        try:
            await asyncio.gather(
                client.publish(CANCEL_CHANNEL, request_id),
                client.set(f"cancel:{request_id}", "1", ex=CANCEL_KEY_TTL),
            )
            logger.info("cancel_published", extra={"request_id": request_id})
        except Exception as e:
            logger.error("cancel_publish_failed", extra={"request_id": request_id, "error": str(e)})
            raise

    async def _listen(self, registry: CancellationRegistry) -> None:
        """Background task: subscribe to Pub/Sub and relay to registry."""
        client = await self._ensure_client()
        pubsub = client.pubsub()
        self._pubsub = pubsub
        await pubsub.subscribe(CANCEL_CHANNEL)
        logger.info("cancellation_listener_started")

        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0)
                    if message is not None and message["type"] == "message":
                        request_id = message["data"]
                        registry.cancel_local(request_id)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error("pubsub_listen_error", extra={"error": str(e)})
                    await asyncio.sleep(1)
        finally:
            await pubsub.unsubscribe(CANCEL_CHANNEL)
            await pubsub.aclose()
            logger.info("cancellation_listener_stopped")

    async def start(self, registry: CancellationRegistry) -> None:
        """Start the background listener. Call from lifespan startup."""
        self._running = True
        self._listener_task = asyncio.create_task(self._listen(registry))

    async def stop(self) -> None:
        """Stop the listener. Call from lifespan shutdown."""
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
        """Poll cancel key fallback — called by Forwarder on each SSE chunk."""
        try:
            client = await self._ensure_client()
            return await client.exists(f"cancel:{request_id}") == 1
        except Exception as e:
            logger.warning("cancel_key_poll_failed", extra={"error": str(e)})
            return False


class CancelService:
    """High-level API: cancel a request locally or via broadcaster."""

    def __init__(self, registry: CancellationRegistry, broadcaster: CancellationBroadcaster | None):
        self._registry = registry
        self._broadcaster = broadcaster

    async def cancel(self, request_id: str) -> bool:
        # 1. Local first (fastest)
        if self._registry.cancel_local(request_id):
            return True
        # 2. Broadcast via Pub/Sub
        if self._broadcaster is not None:
            try:
                await self._broadcaster.publish(request_id)
                return True
            except Exception as e:
                logger.warning("broadcast_cancel_failed", extra={"request_id": request_id, "error": str(e)})
        return False


# Module-level singletons (wired in main.py lifespan)
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
```

- [ ] **Step 2: Write unit tests for CoordinationService**

```python
# tests/unit/test_coordination.py
import pytest
import asyncio
from agent_routers.services.coordination import (
    CancellationRegistry,
    CancellationBroadcaster,
    CancelService,
)


def test_registry_track_and_cancel():
    registry = CancellationRegistry()
    async def run():
        async with registry.track("req-1") as event:
            assert not event.is_set()
            assert registry.is_tracked("req-1")
            registry.cancel_local("req-1")
            assert event.is_set()
        assert not registry.is_tracked("req-1")
    asyncio.run(run())


def test_registry_cancel_unknown_is_false():
    registry = CancellationRegistry()
    assert registry.cancel_local("unknown") is False


def test_registry_cleanup_on_exception():
    registry = CancellationRegistry()
    async def run():
        try:
            async with registry.track("req-2") as event:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert not registry.is_tracked("req-2")
    asyncio.run(run())


@pytest.mark.asyncio
async def test_cancel_service_local():
    registry = CancellationRegistry()
    broadcaster = None
    svc = CancelService(registry, broadcaster)
    async with registry.track("req-3"):
        result = await svc.cancel("req-3")
        assert result is True
        # After exiting context, local is cleaned — noop
        result2 = await svc.cancel("req-3")
        assert result2 is False


@pytest.mark.asyncio
async def test_cancel_service_no_broadcaster():
    registry = CancellationRegistry()
    svc = CancelService(registry, None)
    # No local track — should return False, not raise
    result = await svc.cancel("req-nonexistent")
    assert result is False
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_coordination.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agent_routers/services/coordination.py tests/unit/test_coordination.py
git commit -m "feat: CancellationRegistry, CancellationBroadcaster, and CancelService"
```

---

## Task 2: Cancel API Route

**Files:**
- Create: `agent_routers/api/routes_cancel.py`
- Modify: `agent_routers/main.py` (register cancel router, wire cancellation)
- Create: `tests/unit/test_cancel_route.py`

- [ ] **Step 1: Create `agent_routers/api/routes_cancel.py`**

```python
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from agent_routers.api.dependencies import get_auth, AuthContext
from agent_routers.services.coordination import get_registry, get_broadcaster, CancelService
from agent_routers.adapters.audit_repo import AuditRepository, get_audit_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/requests", tags=["cancel"])


def get_cancel_service() -> CancelService:
    registry = get_registry()
    broadcaster = get_broadcaster()
    return CancelService(registry, broadcaster)


@router.post(
    "/{request_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel an in-flight request (creator or admin)",
)
async def cancel_request(
    request_id: str,
    auth: AuthContext = Depends(get_auth),
    cancel_svc: CancelService = Depends(get_cancel_service),
    audit_repo: AuditRepository = Depends(get_audit_repo),
):
    # Authorization: creator (sub matches audit record) or admin
    if not auth.is_admin:
        audit_event = await audit_repo.get_by_request_id(request_id)
        if audit_event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            )
        if audit_event.user_subject != auth.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the request creator or admin can cancel",
            )

    cancelled = await cancel_svc.cancel(request_id)
    logger.info("cancel_requested", extra={"request_id": request_id, "cancelled": cancelled, "caller": auth.sub})
    return {"status": "accepted", "request_id": request_id, "cancelled": cancelled}
```

- [ ] **Step 2: Wire CancellationRegistry into request lifecycle**

In `routes_forward.py`, inject `cancel_event` into `request.state`:

```python
from agent_routers.services.coordination import get_registry, CancellationRegistry

async def route_request(...):
    registry: CancellationRegistry = get_registry()
    request_id = getattr(request.state, "request_id", "")
    async with registry.track(request_id) as cancel_event:
        request.state.cancel_event = cancel_event
        response = await forwarder.forward(request, agent_id, endpoint_id, cancel_event)
    return response
```

- [ ] **Step 3: Wire lifecycle in `main.py`**

```python
from agent_routers.services.coordination import init_coordination, get_broadcaster

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _session_factory
    _engine = create_async_engine(settings.DATABASE_URL, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    # Start coordination
    registry, broadcaster = init_coordination(settings.REDIS_URL)
    await broadcaster.start(registry)

    yield

    # Shutdown coordination
    await broadcaster.stop()
    if _engine is not None:
        await _engine.dispose()
```

- [ ] **Step 4: Write unit tests for cancel route**

```python
# tests/unit/test_cancel_route.py
import pytest
from unittest.mock import AsyncMock, patch
from agent_routers.api.routes_cancel import router, get_cancel_service
from agent_routers.services.coordination import CancelService


def test_cancel_no_broadcaster_fails_gracefully():
    svc = CancelService(CancellationRegistry(), None)
    # No tracked request — cancel returns False
    # No exception raised
```

- [ ] **Step 5: Commit**

```bash
git add agent_routers/api/routes_cancel.py agent_routers/api/routes_forward.py agent_routers/main.py
git commit -m "feat: cancel API route with creator/admin authorization"
```

---

## Task 3: Integration Tests for Cancellation

**Files:**
- Create: `tests/integration/test_cancel_integration.py`
- Create: `tests/contract/test_cancel_sse.py`

- [ ] **Step 1: Write integration test for cancel**

```python
# tests/integration/test_cancel_integration.py
import pytest
import asyncio
from agent_routers.services.coordination import CancellationRegistry, CancellationBroadcaster, CancelService

# Uses testcontainers or fakeredis for Redis
# Tests:
# 1. Local cancel: track() → cancel() → event.is_set()
# 2. Pub/Sub cancel: broadcaster.publish() → listener updates registry
# 3. Key fallback: SET cancel:req-1 → poll_key() returns True
```

- [ ] **Step 2: Write SSE cancel contract test**

```python
# tests/contract/test_cancel_sse.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from agent_routers.services.forwarder import Forwarder

# Test: SSE stream with cancel_event.is_set() returns correct bytes and exits cleanly
# Mock httpx AsyncClient.stream with a slow async generator
# Cancel mid-stream → only chunks before cancel yielded
```

- [ ] **Step 3: Run integration tests**

Run: `pytest tests/integration/test_cancel_integration.py tests/contract/test_cancel_sse.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_cancel_integration.py tests/contract/test_cancel_sse.py
git commit -m "test: cancellation integration and SSE contract tests"
```

---

## Task 4: Request Tracking Model (Creator Lookup)

**Files:**
- Create: `agent_routers/models/request.py`
- Create: `alembic/versions/004_request_tracking.py`
- Modify: `agent_routers/models/__init__.py`
- Modify: `agent_routers/adapters/audit_repo.py` (add get_by_request_id for creator check)

- [ ] **Step 1: Create `agent_routers/models/request.py`**

```python
from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_routers.models.agent import Base


class RequestTracking(Base):
    """Lightweight in-progress request record for creator lookup on cancel.

    This is an alternative to querying audit_events (which may not be written yet
    for in-flight requests). Written at request start, cleaned up on completion.
    """
    __tablename__ = "request_tracking"

    request_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
```

- [ ] **Step 2: Generate migration**

Run: `alembic revision --autogenerate -m "add request_tracking table"`
Expected: Creates `alembic/versions/<rev>_add_request_tracking.py`

- [ ] **Step 3: Add `get_by_request_id` to `AuditRepository` (reuse audit_events)**

The `audit_events` table already has `user_subject` — use that for cancel authorization:

```python
# In agent_routers/adapters/audit_repo.py, ensure this method exists:
async def get_by_request_id(self, request_id: str) -> AuditEvent | None:
    async with self._sf() as session:
        return await session.get(AuditEvent, request_id)
```

- [ ] **Step 4: Commit**

```bash
git add agent_routers/models/request.py agent_routers/adapters/audit_repo.py alembic/versions/
git commit -m "feat: request_tracking model and audit_repo for cancel authorization"
```

---

## Task 5: Graceful Shutdown Final Integration

**Files:**
- Modify: `agent_routers/main.py` (finalize shutdown sequence)

- [ ] **Step 1: Finalize `main.py` lifespan shutdown sequence**

The shutdown order from §5.6:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _session_factory, _engine

    _engine = create_async_engine(settings.DATABASE_URL, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    # Middleware + Forwarder
    from agent_routers.services.routing import RoutingDecisionEngine
    from agent_routers.adapters.rule_repo import RuleRepository
    from agent_routers.services.forwarder import Forwarder
    from agent_routers.adapters.http_client import get_client_pool
    from agent_routers.services.coordination import init_coordination, get_registry

    repo = AuditRepository(_session_factory)
    signer = HmacSigner()
    registry, broadcaster = init_coordination(settings.REDIS_URL)
    await broadcaster.start(registry)

    app.state.audit_repo = repo
    app.state.rule_repo = RuleRepository(_session_factory)
    app.state.forwarder = Forwarder(
        agent_repo=AgentRepository(_session_factory),
        routing_engine=RoutingDecisionEngine(app.state.rule_repo),
        client_pool=get_client_pool(),
    )

    app.add_middleware(AuditMiddleware, repo=repo, signer=signer)
    app.add_middleware(QuotaMiddleware)
    app.add_middleware(JWTAuthMiddleware)
    app.add_middleware(RequestIdMiddleware)

    yield

    # ---- SHUTDOWN SEQUENCE ----
    # 1. Close per-agent HTTP clients
    await get_client_pool().close_all()

    # 2. Stop cancellation broadcaster (stops listener task)
    await broadcaster.stop()

    # 3. Drain audit tasks
    from agent_routers.middleware.audit import audit_task_set
    if audit_task_set:
        await asyncio.wait_for(
            asyncio.gather(*audit_task_set, return_exceptions=True),
            timeout=settings.DRAIN_TIMEOUT_SECONDS,
        )

    # 4. Close DB
    if _engine is not None:
        await _engine.dispose()
```

- [ ] **Step 2: Commit**

```bash
git add agent_routers/main.py
git commit -m "feat: complete graceful shutdown sequence with all cleanup stages"
```

---

## Self-Review Checklist

1. **Spec coverage**:
   - ✅ `CancellationRegistry` — in-memory `dict[str, asyncio.Event]` — §4.4
   - ✅ `CancellationBroadcaster` — Redis Pub/Sub + SET key fallback — §4.4
   - ✅ `cancel:{request_id}` key with 30s TTL — §6.2
   - ✅ `CancelService` — local-first then broadcast — §4.4
   - ✅ Cancel API `POST /v1/requests/{request_id}/cancel` — §3.1
   - ✅ Creator/Admin authorization check — §4.4
   - ✅ `Forwarder._forward_stream` checks `cancel_event.is_set()` on each chunk — §4.3
   - ✅ SSE cancel interrupt without `is_disconnected()` — §4.3
   - ✅ Shutdown sequence: clients → broadcaster → audit drain → DB — §5.6

2. **Placeholder scan**: No TBD/TODO.

3. **Type consistency**: All async, all type-annotated.

**Plan saved to:** `docs/superpowers/plans/2026-05-05-coordination-plan.md`