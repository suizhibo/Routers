# Remove endpoint_id Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all `endpoint_id` references and replace with `EndpointType` enum across models, services, schemas, and tests.

**Architecture:** Add `EndpointType` enum (`chat`, `create_session`, `stop`). Replace `AgentEndpoint.endpoint_id` with `endpoint_type`. Simplify `RoutingDecisionEngine.resolve()` to return `str` (agent_id only). Session cache stores `agent_id` only. Forwarder hardcodes `EndpointType.CHAT` for normal flow and `EndpointType.CREATE_SESSION` for auto-create.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.x async, Alembic, Pydantic v2, pytest-asyncio

---

## File Map

| File | Responsibility |
|------|---------------|
| `agent_routers/models/agent.py` | `EndpointType` enum + `AgentEndpoint` model |
| `agent_routers/models/rule.py` | `RoutingRule` model — `target_endpoint_type` replaces `target_endpoint_id` |
| `agent_routers/models/audit.py` | `AuditEvent` model — remove `endpoint_id` |
| `agent_routers/schemas/agent.py` | `EndpointSpec` schema — `endpoint_type` replaces `endpoint_id` |
| `agent_routers/services/session_manager.py` | Simplify cache to `agent_id` only |
| `agent_routers/services/routing.py` | `resolve()` returns `str`; remove endpoint from all levels |
| `agent_routers/services/forwarder.py` | `_find_endpoint` by `EndpointType`; hardcode `CHAT`/`CREATE_SESSION` |
| `agent_routers/services/registry.py` | Use `endpoint_type` in agent registration |
| `agent_routers/services/signer.py` | Remove `endpoint_id` from canonical string |
| `agent_routers/adapters/agent_repo.py` | Persist `endpoint_type` instead of `endpoint_id` |
| `agent_routers/adapters/audit_repo.py` | Remove `endpoint_id` from audit persistence |
| `agent_routers/api/routes_audit.py` | Remove `endpoint_id` from response |
| `agent_routers/middleware/audit.py` | Remove `endpoint_id` extraction |
| `alembic/versions/` | DB migration: drop `endpoint_id`, add `endpoint_type` |

---

### Task 1: Add EndpointType Enum

**Files:**
- Modify: `agent_routers/models/agent.py`
- Test: `tests/unit/test_agent_schemas.py` (will be updated in Task 3)

- [ ] **Step 1: Add EndpointType enum to agent.py**

Add at top of `agent_routers/models/agent.py`, after imports:

```python
from enum import Enum


class EndpointType(str, Enum):
    CHAT = "chat"
    CREATE_SESSION = "create_session"
    STOP = "stop"
```

- [ ] **Step 2: Commit enum**

```bash
git add agent_routers/models/agent.py
git commit -m "feat: add EndpointType enum"
```

---

### Task 2: Update AgentEndpoint Model

**Files:**
- Modify: `agent_routers/models/agent.py`
- Test: `tests/unit/test_forwarder.py`, `tests/unit/test_auto_session.py`, `tests/unit/test_routing.py`

- [ ] **Step 1: Replace endpoint_id with endpoint_type**

In `agent_routers/models/agent.py`, change `AgentEndpoint`:

```python
class AgentEndpoint(Base):
    __tablename__ = "agent_endpoints"

    agent_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True
    )
    endpoint_type: Mapped[str] = mapped_column(String(16), primary_key=True)
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

- [ ] **Step 2: Update test fixtures to use endpoint_type**

In `tests/unit/test_forwarder.py`, update `_make_agent`:

```python
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
            endpoint_type="chat",
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
```

In `tests/unit/test_auto_session.py`, update `_make_agent_with_create_session`:

```python
def _make_agent_with_create_session() -> Agent:
    agent = Agent(
        agent_id="weather-agent",
        name="Weather Agent",
        subject="svc-weather",
    )
    agent.instances = [
        AgentInstance(agent_id="weather-agent", instance_id="inst-1", base_url="http://localhost:8001", weight=1),
    ]
    agent.endpoints = [
        AgentEndpoint(
            agent_id="weather-agent",
            endpoint_type="create_session",
            method="POST",
            path="/sessions",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={},
            session_config={"response_body_path": "data.id"},
        ),
        AgentEndpoint(
            agent_id="weather-agent",
            endpoint_type="chat",
            method="POST",
            path="/chat/{session_id}",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="stream",
            idempotent=False,
            param_mapping={"path_params": {"session_id": "context.session_id"}},
            session_config=None,
        ),
    ]
    return agent
```

In `tests/unit/test_routing.py`, update `_make_agent`:

```python
def _make_agent(agent_id: str, endpoint_type: str) -> Agent:
    agent = Agent(agent_id=agent_id, name=f"Agent {agent_id}", subject=f"sub-{agent_id}")
    agent.instances = [AgentInstance(agent_id=agent_id, instance_id="inst-1", base_url="http://localhost:8001", weight=1)]
    agent.endpoints = [
        AgentEndpoint(
            agent_id=agent_id,
            endpoint_type=endpoint_type,
            method="POST",
            path="/chat",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={},
            session_config=None,
        ),
    ]
    return agent
```

- [ ] **Step 3: Run tests to verify model changes compile**

```bash
python3 -m pytest tests/unit/test_forwarder.py tests/unit/test_auto_session.py tests/unit/test_routing.py -v --collect-only
```

Expected: Tests collect without import errors (will fail at runtime due to other code still using endpoint_id).

- [ ] **Step 4: Commit**

```bash
git add agent_routers/models/agent.py tests/unit/test_forwarder.py tests/unit/test_auto_session.py tests/unit/test_routing.py
git commit -m "refactor: replace endpoint_id with endpoint_type in AgentEndpoint model and test fixtures"
```

---

### Task 3: Update RoutingRule and AuditEvent Models

**Files:**
- Modify: `agent_routers/models/rule.py`
- Modify: `agent_routers/models/audit.py`
- Modify: `agent_routers/schemas/agent.py`

- [ ] **Step 1: Update RoutingRule model**

In `agent_routers/models/rule.py`:

```python
class RoutingRule(Base):
    __tablename__ = "routing_rules"

    rule_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    priority: Mapped[int] = mapped_column(default=0)
    when_clause: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    target_agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_endpoint_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 2: Remove endpoint_id from AuditEvent**

In `agent_routers/models/audit.py`:

```python
class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    user_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    signature: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_event: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
```

- [ ] **Step 3: Update EndpointSpec schema**

In `agent_routers/schemas/agent.py`:

```python
class EndpointSpec(BaseModel):
    endpoint_type: str  # "chat", "create_session", or "stop"
    method: str
    path: str
    mode: str  # "block" | "stream"
    param_mapping: dict = Field(default_factory=dict)
    session_config: dict | None = None
```

- [ ] **Step 4: Commit models and schemas**

```bash
git add agent_routers/models/rule.py agent_routers/models/audit.py agent_routers/schemas/agent.py
git commit -m "refactor: update RoutingRule, AuditEvent, and EndpointSpec schemas"
```

---

### Task 4: Write DB Migration

**Files:**
- Create: `alembic/versions/`

- [ ] **Step 1: Generate migration**

```bash
alembic revision --autogenerate -m "replace endpoint_id with endpoint_type"
```

- [ ] **Step 2: Review and fix generated migration**

Open the generated file in `alembic/versions/`. Ensure it:
1. Drops `endpoint_id` from `agent_endpoints`
2. Adds `endpoint_type` to `agent_endpoints` (String(16), part of PK)
3. Drops `target_endpoint_id` from `routing_rules`
4. Adds `target_endpoint_type` to `routing_rules` (String(16), nullable)
5. Drops `endpoint_id` from `audit_events`

Manually fix if Alembic doesn't detect correctly.

- [ ] **Step 3: Run migration locally**

```bash
alembic upgrade head
```

- [ ] **Step 4: Commit migration**

```bash
git add alembic/versions/
git commit -m "migration: replace endpoint_id with endpoint_type"
```

---

### Task 5: Update SessionManager

**Files:**
- Modify: `agent_routers/services/session_manager.py`
- Test: `tests/unit/test_session_manager.py`

- [ ] **Step 1: Simplify set_route and get_route**

In `agent_routers/services/session_manager.py`:

```python
class SessionManager:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    async def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def get_route(self, session_id: str) -> str | None:
        if not session_id:
            return None
        try:
            client = await self._ensure_client()
            return await client.get(f"session:{session_id}")
        except Exception:
            logger.exception("session_get_failed", extra={"session_id": session_id})
            return None

    async def set_route(
        self,
        session_id: str,
        agent_id: str,
        ttl: int = DEFAULT_TTL,
    ) -> None:
        if not session_id or not agent_id:
            return
        try:
            client = await self._ensure_client()
            await client.set(f"session:{session_id}", agent_id, ex=ttl)
            logger.info("session_set", extra={"session_id": session_id, "agent_id": agent_id})
        except Exception:
            logger.exception("session_set_failed", extra={"session_id": session_id, "agent_id": agent_id})
```

- [ ] **Step 2: Update session manager tests**

In `tests/unit/test_session_manager.py`, update `test_set_route` and `test_get_route_found`:

```python
@pytest.mark.asyncio
async def test_set_route():
    mgr = SessionManager(redis_url="redis://localhost:6379")
    mock_redis = AsyncMock(spec=redis.Redis)
    mock_redis.set = AsyncMock(return_value=True)
    mgr._client = mock_redis

    await mgr.set_route("sess-123", "agent-a")
    mock_redis.set.assert_awaited_once_with("session:sess-123", "agent-a", ex=86400)


@pytest.mark.asyncio
async def test_get_route_found():
    mgr = SessionManager(redis_url="redis://localhost:6379")
    mock_redis = AsyncMock(spec=redis.Redis)
    mock_redis.get = AsyncMock(return_value="agent-a")
    mgr._client = mock_redis

    result = await mgr.get_route("sess-123")
    assert result == "agent-a"
```

- [ ] **Step 3: Run session manager tests**

```bash
python3 -m pytest tests/unit/test_session_manager.py -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add agent_routers/services/session_manager.py tests/unit/test_session_manager.py
git commit -m "refactor: simplify SessionManager to agent_id only"
```

---

### Task 6: Update RoutingDecisionEngine

**Files:**
- Modify: `agent_routers/services/routing.py`
- Test: `tests/unit/test_routing.py`

- [ ] **Step 1: Update resolve() to return str**

In `agent_routers/services/routing.py`:

```python
class RoutingDecisionEngine:
    ...

    async def resolve(
        self,
        route_req: RouteRequest,
        headers: dict[str, str],
    ) -> str:
        req_dict = route_req.model_dump()

        # L1: Preferred
        preferred_agent = headers.get("X-Preferred-Agent")
        if preferred_agent:
            logger.debug("routing_l1_preferred", extra={"agent": preferred_agent})
            return preferred_agent

        # L2: Cache
        session_id = _extract_value(req_dict, "context.session_id")
        if session_id and self._session_manager:
            cached_agent_id = await self._session_manager.get_route(session_id)
            if cached_agent_id:
                logger.debug("routing_l2_cache", extra={"session_id": session_id, "agent": cached_agent_id})
                return cached_agent_id

        # L3: Rule
        rules = await self._rule_repo.list_enabled()
        for rule in rules:
            if _evaluate_when_clause(rule.when_clause, route_req, headers):
                logger.debug("routing_l3_rule", extra={"rule_id": rule.rule_id, "agent": rule.target_agent_id})
                return rule.target_agent_id

        # L4: Default
        if self._default_agent_id:
            logger.debug("routing_l4_default", extra={"agent": self._default_agent_id})
            return self._default_agent_id

        from agent_routers.errors import AgentNotFoundError
        raise AgentNotFoundError("No route found for request")
```

- [ ] **Step 2: Update routing tests**

In `tests/unit/test_routing.py`:

Update `FakeSessionManager` if it exists to return `str` instead of `tuple`.

Update all test assertions. For example:

```python
# Before: assert result == ("agent-a", "chat")
# After:
assert result == "agent-a"
```

Update `test_l1_preferred_header_wins`:
```python
@pytest.mark.asyncio
async def test_l1_preferred_header_wins():
    engine = _make_engine()
    req = RouteRequest()
    headers = {"X-Preferred-Agent": "agent-a"}
    result = await engine.resolve(req, headers)
    assert result == "agent-a"
```

Update `test_l1_preferred_without_agent_ignored`:
```python
@pytest.mark.asyncio
async def test_l1_preferred_without_agent_ignored():
    engine = _make_engine()
    req = RouteRequest()
    headers = {}
    with pytest.raises(AgentNotFoundError):
        await engine.resolve(req, headers)
```

Update `test_l2_cache_hit`:
```python
@pytest.mark.asyncio
async def test_l2_cache_hit():
    engine = _make_engine(session_route="agent-a")
    req = RouteRequest(context={"session_id": "sess-123"})
    result = await engine.resolve(req, {})
    assert result == "agent-a"
```

Update `_make_engine` to accept `session_route` as `str` instead of `tuple`.

- [ ] **Step 3: Run routing tests**

```bash
python3 -m pytest tests/unit/test_routing.py -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add agent_routers/services/routing.py tests/unit/test_routing.py
git commit -m "refactor: RoutingDecisionEngine.resolve returns agent_id only"
```

---

### Task 7: Update Forwarder

**Files:**
- Modify: `agent_routers/services/forwarder.py`
- Test: `tests/unit/test_forwarder.py`, `tests/unit/test_auto_session.py`

- [ ] **Step 1: Update _find_endpoint to search by endpoint_type**

In `agent_routers/services/forwarder.py`:

```python
    @staticmethod
    def _find_endpoint(agent: Agent, endpoint_type: str) -> AgentEndpoint:
        for ep in agent.endpoints:
            if ep.endpoint_type == endpoint_type:
                return ep
        raise EndpointNotFoundError(
            f"Endpoint '{endpoint_type}' not found on agent '{agent.agent_id}'"
        )
```

- [ ] **Step 2: Update forward() and _auto_create_session**

In `forward()`:

```python
    async def forward(...):
        session_id = route_req.context.get("session_id")

        agent_id = await self._routing_engine.resolve(
            route_req, dict(request.headers)
        )

        if not session_id:
            session_id = await self._auto_create_session(request, route_req, agent_id)
            route_req.context["session_id"] = session_id

        agent = await self._agent_repo.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not registered")

        endpoint = self._find_endpoint(agent, "chat")
        ...
```

In `_auto_create_session()`:

```python
    async def _auto_create_session(...):
        ...
        endpoint = self._find_endpoint(agent, "create_session")
        ...
```

- [ ] **Step 3: Remove endpoint_id from _extract_session_id and set_route call**

In `_auto_create_session`, update the set_route call:

```python
        if self._session_manager:
            await self._session_manager.set_route(session_id, agent_id)
```

- [ ] **Step 4: Update forwarder tests**

In `tests/unit/test_forwarder.py`, update `FakeRoutingEngine`:

```python
class FakeRoutingEngine:
    def __init__(self, result: str):
        self._result = result

    async def resolve(self, route_req: RouteRequest, headers: dict) -> str:
        return self._result
```

Update all test instantiations from `FakeRoutingEngine(("agent-1", "chat"))` to `FakeRoutingEngine("agent-1")`.

Update `test_forwarder.py` tests to pass `endpoint_type="chat"` in `_make_agent` (already done in Task 2).

In `tests/unit/test_auto_session.py`:
- Update `FakeRoutingEngine` similarly
- Update engine instantiations from `FakeRoutingEngine(("weather-agent", "chat"))` to `FakeRoutingEngine("weather-agent")`
- Update `test_auto_create_session_then_chat` assertions: `set_route` now takes `(session_id, agent_id)` instead of `(agent_id, session_id, endpoint_id)` — but wait, the set_route bug was already there. With Task 5, set_route now takes `(session_id, agent_id)` in correct order.

Wait, I need to check the current set_route call in forwarder after Task 5. In Task 5, set_route signature is `(session_id, agent_id, ttl)`. And forwarder calls `await self._session_manager.set_route(agent_id, session_id, endpoint.endpoint_id)` which was wrong order. Now with endpoint removed, the call should be `await self._session_manager.set_route(session_id, agent_id)` which matches the correct order!

So this change actually fixes the set_route argument order bug as a side effect.

Update `test_auto_session.py` assertions:
```python
# Before: mock_session_mgr.set_route.assert_awaited_once_with("weather-agent", "sess-abc123", "create-session")
# After: 
mock_session_mgr.set_route.assert_awaited_once_with("sess-abc123", "weather-agent")
```

- [ ] **Step 5: Run forwarder and auto-session tests**

```bash
python3 -m pytest tests/unit/test_forwarder.py tests/unit/test_auto_session.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add agent_routers/services/forwarder.py tests/unit/test_forwarder.py tests/unit/test_auto_session.py
git commit -m "refactor: forwarder uses EndpointType, resolve returns agent_id only"
```

---

### Task 8: Update Registry, Signer, and Adapters

**Files:**
- Modify: `agent_routers/services/registry.py`
- Modify: `agent_routers/services/signer.py`
- Modify: `agent_routers/adapters/agent_repo.py`
- Modify: `agent_routers/adapters/audit_repo.py`
- Test: `tests/unit/test_registry_service.py`, `tests/unit/test_signer.py`

- [ ] **Step 1: Update registry to use endpoint_type**

In `agent_routers/services/registry.py`, update the endpoint creation loop:

```python
for ep in spec.endpoints:
    agent.endpoints.append(
        AgentEndpoint(
            agent_id=agent.agent_id,
            endpoint_type=ep.endpoint_type,
            method=ep.method,
            path=ep.path,
            path_params=[],
            query_params=[],
            body_schema=None,
            mode=ep.mode,
            idempotent=False,
            param_mapping=ep.param_mapping,
            session_config=ep.session_config,
        )
    )
```

- [ ] **Step 2: Update signer to remove endpoint_id**

In `agent_routers/services/signer.py`:

```python
class AuditSigner:
    @staticmethod
    def canonical(
        request_id: str,
        timestamp_iso: str,
        user_subject: str,
        agent_id: str,
        status_code: int,
        latency_ms: int,
    ) -> str:
        return f"{request_id}|{timestamp_iso}|{user_subject}|{agent_id}|{status_code}|{latency_ms}"
```

- [ ] **Step 3: Update agent_repo adapter**

In `agent_routers/adapters/agent_repo.py`, update the endpoint mapping:

```python
AgentEndpoint(
    agent_id=agent.agent_id,
    endpoint_type=ep.endpoint_type,
    ...
)
```

- [ ] **Step 4: Update audit_repo adapter**

In `agent_routers/adapters/audit_repo.py`, remove `endpoint_id` from the insert:

```python
async def save(self, event: dict) -> None:
    audit = AuditEvent(
        event_id=event["event_id"],
        request_id=event["request_id"],
        timestamp=event["timestamp"],
        user_subject=event["user_subject"],
        agent_id=event.get("agent_id"),
        status_code=event.get("status_code"),
        latency_ms=event.get("latency_ms"),
        signature=event.get("signature"),
        raw_event=event,
    )
    self._session.add(audit)
    await self._session.commit()
```

- [ ] **Step 5: Update registry and signer tests**

In `tests/unit/test_registry_service.py`, update endpoint specs:

```python
endpoints=[EndpointSpec(endpoint_type="chat", method="GET", path="/", mode="block")]
```

In `tests/unit/test_signer.py`, update canonical test:

```python
def test_canonical_format():
    signer = AuditSigner(secret="test-secret")
    result = signer.canonical(
        request_id="req-1",
        timestamp_iso="2024-01-01T00:00:00Z",
        user_subject="user-1",
        agent_id="agent-1",
        status_code=200,
        latency_ms=100,
    )
    assert result == "req-1|2024-01-01T00:00:00Z|user-1|agent-1|200|100"
```

- [ ] **Step 6: Run tests**

```bash
python3 -m pytest tests/unit/test_registry_service.py tests/unit/test_signer.py -v
```

- [ ] **Step 7: Commit**

```bash
git add agent_routers/services/registry.py agent_routers/services/signer.py agent_routers/adapters/agent_repo.py agent_routers/adapters/audit_repo.py tests/unit/test_registry_service.py tests/unit/test_signer.py
git commit -m "refactor: update registry, signer, and adapters for endpoint_type"
```

---

### Task 9: Update API and Middleware

**Files:**
- Modify: `agent_routers/api/routes_audit.py`
- Modify: `agent_routers/middleware/audit.py`

- [ ] **Step 1: Remove endpoint_id from audit response**

In `agent_routers/api/routes_audit.py`:

```python
return {
    "event_id": event.event_id,
    "request_id": event.request_id,
    "timestamp": event.timestamp.isoformat(),
    "user_subject": event.user_subject,
    "agent_id": event.agent_id,
    "status_code": event.status_code,
    "latency_ms": event.latency_ms,
    "signature": event.signature,
}
```

- [ ] **Step 2: Remove endpoint_id from audit middleware**

In `agent_routers/middleware/audit.py`:

```python
# Remove these lines:
# endpoint_id = request.path_params.get("endpoint_id", "")

audit_event = {
    "event_id": str(uuid.uuid4()),
    "request_id": request_id,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "user_subject": user_subject,
    "agent_id": agent_id,
    "status_code": status_code,
    "latency_ms": latency_ms,
    "signature": signature,
}
```

- [ ] **Step 3: Commit**

```bash
git add agent_routers/api/routes_audit.py agent_routers/middleware/audit.py
git commit -m "refactor: remove endpoint_id from audit API and middleware"
```

---

### Task 10: Update Agent Schema Tests

**Files:**
- Modify: `tests/unit/test_agent_schemas.py`

- [ ] **Step 1: Update schema test assertions**

In `tests/unit/test_agent_schemas.py`, replace all `endpoint_id` with `endpoint_type`:

```python
endpoints=[
    EndpointSpec(
        endpoint_type="chat",
        method="GET",
        path="/forecast",
        mode="block",
    )
]
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/unit/test_agent_schemas.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_agent_schemas.py
git commit -m "test: update agent schema tests for endpoint_type"
```

---

### Task 11: Full Test Suite Verification

- [ ] **Step 1: Run all unit tests**

```bash
python3 -m pytest tests/unit/ -v
```

Expected: All pass.

- [ ] **Step 2: Run lint on modified files**

```bash
python3 -m ruff check agent_routers/services/forwarder.py agent_routers/services/routing.py agent_routers/services/session_manager.py agent_routers/services/registry.py agent_routers/services/signer.py
```

Expected: No new errors.

- [ ] **Step 3: Run type check on modified files**

```bash
python3 -m mypy agent_routers/services/forwarder.py agent_routers/services/routing.py agent_routers/services/session_manager.py
```

Expected: No new errors (pre-existing errors in other files are OK).

- [ ] **Step 4: Commit verification**

```bash
git commit -m "test: all tests pass after endpoint_id removal" --allow-empty
```

---

### Task 12: Update Documentation

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Update AGENTS.md**

Update sections:
- Routing Pipeline: L1 uses only `X-Preferred-Agent`, resolve returns agent_id
- Session Extraction: session cache stores agent_id only
- Forwarder signature: no endpoint references
- Common Pitfalls: remove forwarder signature warning about endpoint

- [ ] **Step 2: Commit docs**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md for endpoint_id removal"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Every spec requirement has a corresponding task
- [x] **Placeholder scan:** No TBD, TODO, or vague steps
- [x] **Type consistency:** `EndpointType` / `endpoint_type` used consistently across all tasks
- [x] **Test coverage:** Each modified service has corresponding test updates in the same or adjacent task

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-06-remove-endpoint-id.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
