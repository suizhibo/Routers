# Agent Authentication Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-agent authentication credentials (`auth_header` + `auth_token`) so the Forwarder can inject them when calling upstream agents, while masking the token in API responses.

**Architecture:** Store two nullable columns on the `agents` table (`auth_header`, `auth_token`). The Forwarder injects them into upstream request headers. The registry service masks `auth_token` as `"***"` in `AgentDetail` and omits it from `AgentListItem`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, Alembic, httpx, pytest

---

## File Map

| File | Responsibility |
|------|---------------|
| `agent_routers/models/agent.py` | SQLAlchemy ORM model — add `auth_header` and `auth_token` columns |
| `agent_routers/schemas/agent.py` | Pydantic request/response schemas — add fields to `AgentRegistration`, `AgentDetail`, `AgentListItem` |
| `agent_routers/adapters/agent_repo.py` | SQLAlchemy CRUD — persist new fields on `create()` |
| `agent_routers/services/registry.py` | Business logic — mask `auth_token` as `"***"` in `get_agent()`, omit from `list_agents()` |
| `agent_routers/services/forwarder.py` | HTTP forwarding — inject `auth_header: auth_token` into upstream requests |
| `tests/unit/test_forwarder.py` | Forwarder unit tests — mock upstream calls, verify header injection |
| `tests/unit/test_agent_schemas.py` | Schema validation tests — optional auth fields parse correctly |
| `tests/integration/test_agent_api.py` | End-to-end tests — register with auth, verify detail/list masking |
| `alembic/versions/` | Auto-generated migration adding columns to `agents` table |
| `schema.sql` | Canonical DDL — add new columns |
| `examples/agents/intelligent-kb-agent.json` | Example agent config — add auth fields |

---

## Current State (read these before editing)

**`agent_routers/models/agent.py`** — `Agent` class currently has:
```python
agent_id, name, subject, created_at, updated_at, base_url, capability, description, endpoints
```

**`agent_routers/schemas/agent.py`** — `AgentRegistration` currently:
```python
agent_id, name, subject, base_url, capability, description, endpoints
```
`AgentDetail` has `agent_id, name, subject, base_url, capability, description, endpoints, created_at, updated_at`.
`AgentListItem` has `agent_id, name, subject, capability, description, created_at`.

**`agent_routers/services/forwarder.py`** — `forward()` passes `dict(request.headers)` to upstream. `_auto_create_session()` passes `dict(request.headers)` too.

**`agent_routers/services/registry.py`** — `get_agent()` reads `agent.endpoints` and builds `AgentDetail` manually. `list_agents()` does `AgentListItem.model_validate(a)`.

---

### Task 1: Update Agent SQLAlchemy Model

**Files:**
- Modify: `agent_routers/models/agent.py`

- [ ] **Step 1: Add `auth_header` and `auth_token` columns**

After the `description` column, add:

```python
    auth_header: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
```

The full `Agent` class should look like:

```python
class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    capability: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_header: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    endpoints: Mapped[list[AgentEndpoint]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
```

- [ ] **Step 2: Commit**

```bash
git add agent_routers/models/agent.py
git commit -m "feat: add auth_header and auth_token to Agent model"
```

---

### Task 2: Update Pydantic Schemas

**Files:**
- Modify: `agent_routers/schemas/agent.py`

- [ ] **Step 1: Add auth fields to `AgentRegistration`**

After the `description` field in `AgentRegistration`, add:

```python
    auth_header: str | None = Field(default=None, max_length=255)
    auth_token: str | None = Field(default=None, max_length=2048)
```

The full `AgentRegistration` should be:

```python
class AgentRegistration(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    capability: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None)
    auth_header: str | None = Field(default=None, max_length=255)
    auth_token: str | None = Field(default=None, max_length=2048)
    endpoints: Annotated[list[EndpointSpec], Field(min_length=1)]
```

- [ ] **Step 2: Add auth fields to `AgentDetail`**

After the `description` field in `AgentDetail`, add:

```python
    capability: str | None
    description: str | None
    auth_header: str | None
    auth_token: str | None
```

The full `AgentDetail` should be:

```python
class AgentDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    name: str
    subject: str
    base_url: str
    capability: str | None
    description: str | None
    auth_header: str | None
    auth_token: str | None
    endpoints: list[EndpointSpec]
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3: Add `auth_header` to `AgentListItem` (omit `auth_token`)**

After the `description` field in `AgentListItem`, add:

```python
    capability: str | None
    description: str | None
    auth_header: str | None
```

The full `AgentListItem` should be:

```python
class AgentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    name: str
    subject: str
    capability: str | None
    description: str | None
    auth_header: str | None
    created_at: datetime
```

- [ ] **Step 4: Commit**

```bash
git add agent_routers/schemas/agent.py
git commit -m "feat: add auth fields to agent schemas"
```

---

### Task 3: Update AgentRepository

**Files:**
- Modify: `agent_routers/adapters/agent_repo.py`

- [ ] **Step 1: Persist auth fields in `create()`**

In `AgentRepository.create()`, when constructing the `Agent` object, add `auth_header` and `auth_token`:

```python
            agent = Agent(
                agent_id=registration.agent_id,
                name=registration.name,
                subject=registration.subject,
                base_url=registration.base_url,
                capability=registration.capability,
                description=registration.description,
                auth_header=registration.auth_header,
                auth_token=registration.auth_token,
            )
```

- [ ] **Step 2: Commit**

```bash
git add agent_routers/adapters/agent_repo.py
git commit -m "feat: persist auth fields in AgentRepository.create"
```

---

### Task 4: Update Registry Service (Token Masking)

**Files:**
- Modify: `agent_routers/services/registry.py`

- [ ] **Step 1: Write test for `get_agent()` token masking**

Open `tests/unit/test_registry_service.py` and add a new test after `test_get_agent_not_found`:

```python
@pytest.mark.asyncio
async def test_get_agent_masks_auth_token(registry, mock_repo):
    from datetime import datetime, timezone
    from agent_routers.models.agent import Agent

    mock_agent = AsyncMock(spec=Agent)
    mock_agent.agent_id = "agent-1"
    mock_agent.name = "Test Agent"
    mock_agent.subject = "sub-1"
    mock_agent.base_url = "http://localhost:8000"
    mock_agent.capability = None
    mock_agent.description = None
    mock_agent.auth_header = "x-api-key"
    mock_agent.auth_token = "secret-123"
    mock_agent.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_agent.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_agent.endpoints = []
    mock_repo.get_by_id.return_value = mock_agent

    result = await registry.get_agent("agent-1")
    assert result.auth_header == "x-api-key"
    assert result.auth_token == "***"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/unit/test_registry_service.py::test_get_agent_masks_auth_token -v
```

Expected: FAIL — `AssertionError` because `auth_token` is `"secret-123"` not `"***"`.

- [ ] **Step 3: Implement token masking in `get_agent()`**

In `agent_routers/services/registry.py`, in the `get_agent()` method, when constructing `AgentDetail`, pass `auth_token="***"` if the agent has one:

```python
        return AgentDetail(
            agent_id=agent.agent_id,
            name=agent.name,
            subject=agent.subject,
            base_url=agent.base_url,
            capability=agent.capability,
            description=agent.description,
            auth_header=agent.auth_header,
            auth_token="***" if agent.auth_token else None,
            endpoints=endpoints,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/unit/test_registry_service.py::test_get_agent_masks_auth_token -v
```

Expected: PASS.

- [ ] **Step 5: Write test for `list_agents()` omitting token**

Add a new test:

```python
@pytest.mark.asyncio
async def test_list_agents_omits_auth_token(registry, mock_repo):
    from datetime import datetime, timezone
    from agent_routers.models.agent import Agent

    mock_agent = AsyncMock(spec=Agent)
    mock_agent.agent_id = "agent-1"
    mock_agent.name = "Test Agent"
    mock_agent.subject = "sub-1"
    mock_agent.capability = None
    mock_agent.description = None
    mock_agent.auth_header = "x-api-key"
    mock_agent.auth_token = "secret-123"
    mock_agent.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_repo.list_agents.return_value = [mock_agent]

    result = await registry.list_agents()
    assert len(result) == 1
    assert result[0].auth_header == "x-api-key"
    assert not hasattr(result[0], "auth_token")
```

- [ ] **Step 6: Run test to verify it fails**

```bash
python3 -m pytest tests/unit/test_registry_service.py::test_list_agents_omits_auth_token -v
```

Expected: FAIL — `AttributeError` or assertion failure because `AgentListItem` has `auth_token` field.

Wait — `AgentListItem` currently does NOT have `auth_token`, so `not hasattr(result[0], "auth_token")` should pass. Actually, the test will pass because `auth_token` is not in `AgentListItem`. Let me revise the test:

The test should just verify that `AgentListItem` does not include `auth_token`. Since we removed it from the schema, the test is really just confirming `AgentListItem.model_validate()` works without `auth_token`. So the test should pass immediately.

Actually, since `AgentListItem` doesn't have `auth_token`, `result[0].auth_token` would raise `AttributeError`. So:

```python
    with pytest.raises(AttributeError):
        _ = result[0].auth_token
```

- [ ] **Step 7: Verify `list_agents()` already passes (no code change needed)**

`list_agents()` does `AgentListItem.model_validate(a)`, and since `AgentListItem` has no `auth_token` field, the token is already excluded. No code change needed.

- [ ] **Step 8: Run test to verify it passes**

```bash
python3 -m pytest tests/unit/test_registry_service.py::test_list_agents_omits_auth_token -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add agent_routers/services/registry.py tests/unit/test_registry_service.py
git commit -m "feat: mask auth_token in AgentDetail, omit from AgentListItem"
```

---

### Task 5: Update Forwarder (Auth Header Injection)

**Files:**
- Modify: `agent_routers/services/forwarder.py`

- [ ] **Step 1: Write test for auth header injection in `forward()`**

Open `tests/unit/test_forwarder.py` and add a new test:

```python
@pytest.mark.asyncio
async def test_forward_injects_auth_headers(pool):
    agent = _make_agent("block")
    agent.auth_header = "x-api-key"
    agent.auth_token = "secret-123"
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
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

    request = _make_request(body=b'{"msg":"hi"}')
    route_req = RouteRequest(context={"session_id": "sess-123"})
    response = await fwd.forward(request, route_req, None)

    assert response.status_code == 200
    call_kwargs = mock_client.request.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "secret-123"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/unit/test_forwarder.py::test_forward_injects_auth_headers -v
```

Expected: FAIL — `KeyError` because `"x-api-key"` is not in the headers dict passed to `client.request()`.

- [ ] **Step 3: Implement auth injection in `forward()`**

In `agent_routers/services/forwarder.py`, in the `forward()` method, after building `full_url` and before calling `_forward_block()` / `_forward_stream()`, inject the auth headers:

Find this block in `forward()`:
```python
        # Build request
        url_path, body_bytes = self._build_request(route_req, endpoint)
        base_url = agent.base_url
        full_url = f"{base_url.rstrip('/')}/{url_path.lstrip('/')}"
```

After it, add:
```python
        # Inject agent auth headers
        upstream_headers = dict(request.headers)
        if agent.auth_header and agent.auth_token:
            upstream_headers[agent.auth_header] = agent.auth_token
```

Then change the two calls:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/unit/test_forwarder.py::test_forward_injects_auth_headers -v
```

Expected: PASS.

- [ ] **Step 5: Write test for auth header overriding downstream**

```python
@pytest.mark.asyncio
async def test_forward_auth_overrides_downstream_header(pool):
    agent = _make_agent("block")
    agent.auth_header = "x-api-key"
    agent.auth_token = "agent-secret"
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b'{"ok": true}'
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-api-key", b"downstream-secret"),
        ],
        "path": "/v1/route",
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    request._body = b'{}'
    route_req = RouteRequest(context={"session_id": "sess-123"})
    await fwd.forward(request, route_req, None)

    call_kwargs = mock_client.request.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "agent-secret"
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python3 -m pytest tests/unit/test_forwarder.py::test_forward_auth_overrides_downstream_header -v
```

Expected: PASS (the agent token should already override because `upstream_headers = dict(request.headers)` followed by `upstream_headers[agent.auth_header] = agent.auth_token` overwrites the key).

- [ ] **Step 7: Implement auth injection in `_auto_create_session()`**

In `_auto_create_session()`, change the upstream call:

Find:
```python
        upstream = await client.request(
            endpoint.method, full_url,
            headers=dict(request.headers), content=body_bytes
        )
```

Replace with:
```python
        session_headers = dict(request.headers)
        if agent.auth_header and agent.auth_token:
            session_headers[agent.auth_header] = agent.auth_token

        upstream = await client.request(
            endpoint.method, full_url,
            headers=session_headers, content=body_bytes
        )
```

- [ ] **Step 8: Write test for `_auto_create_session()` injection**

```python
@pytest.mark.asyncio
async def test_auto_create_session_injects_auth(pool):
    from agent_routers.schemas.agent import EndpointSpec, ParamMapping, SessionConfig

    agent = _make_agent("block")
    agent.endpoints.append(
        AgentEndpoint(
            agent_id="agent-1",
            endpoint_type="create_session",
            method="POST",
            path="/sessions",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={"path_params": {}, "query_params": {}, "body": None},
            session_config={"response_header": None, "response_body_path": "data.id"},
        )
    )
    agent.auth_header = "x-api-key"
    agent.auth_token = "secret-123"
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool, session_manager=None)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json = MagicMock(return_value={"data": {"id": "sess-new"}})
    mock_response.headers = {"content-type": "application/json"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request = _make_request()
    route_req = RouteRequest()
    session_id = await fwd._auto_create_session(request, route_req, "agent-1")

    assert session_id == "sess-new"
    call_kwargs = mock_client.request.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "secret-123"
```

- [ ] **Step 9: Run test to verify it passes**

```bash
python3 -m pytest tests/unit/test_forwarder.py::test_auto_create_session_injects_auth -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add agent_routers/services/forwarder.py tests/unit/test_forwarder.py
git commit -m "feat: inject agent auth headers into upstream requests"
```

---

### Task 6: Create Alembic Migration

**Files:**
- Create: `alembic/versions/XXX_add_agent_auth_fields.py`

- [ ] **Step 1: Create empty Alembic revision**

```bash
alembic revision -m "add_agent_auth_fields"
```

Note the generated filename (e.g., `alembic/versions/ab123cd_add_agent_auth_fields.py`).

- [ ] **Step 2: Fill in upgrade/downgrade**

Edit the generated file. In `upgrade()`:

```python
def upgrade() -> None:
    op.add_column('agents', sa.Column('auth_header', sa.String(length=255), nullable=True))
    op.add_column('agents', sa.Column('auth_token', sa.String(length=2048), nullable=True))
```

In `downgrade()`:

```python
def downgrade() -> None:
    op.drop_column('agents', 'auth_token')
    op.drop_column('agents', 'auth_header')
```

- [ ] **Step 3: Apply migration**

```bash
alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/XXX_add_agent_auth_fields.py
git commit -m "feat: add alembic migration for auth fields"
```

---

### Task 7: Add Schema Unit Tests

**Files:**
- Modify: `tests/unit/test_agent_schemas.py`

- [ ] **Step 1: Write test for optional auth fields**

Add to `tests/unit/test_agent_schemas.py`:

```python
def test_agent_registration_with_auth_fields():
    reg = AgentRegistration(
        agent_id="kb-agent",
        name="KB Agent",
        subject="svc-kb",
        base_url="https://kb:8080",
        auth_header="x-api-key",
        auth_token="secret-123",
        endpoints=[
            EndpointSpec(
                endpoint_type="chat",
                method="POST",
                path="/api/chat",
                mode="block",
                idempotent=False,
                param_mapping=ParamMapping(path_params={}, query_params={}, body=None),
                session_config=None,
            ),
        ],
    )
    assert reg.auth_header == "x-api-key"
    assert reg.auth_token == "secret-123"


def test_agent_registration_without_auth_fields():
    reg = AgentRegistration(
        agent_id="minimal-agent",
        name="Minimal Agent",
        subject="svc-minimal",
        base_url="http://localhost:8001",
        endpoints=[
            EndpointSpec(
                endpoint_type="chat",
                method="GET",
                path="/",
                mode="block",
                idempotent=False,
            ),
        ],
    )
    assert reg.auth_header is None
    assert reg.auth_token is None
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/unit/test_agent_schemas.py -v
```

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_agent_schemas.py
git commit -m "test: add unit tests for auth fields in schemas"
```

---

### Task 8: Add Integration Tests

**Files:**
- Modify: `tests/integration/test_agent_api.py`

- [ ] **Step 1: Write integration test for auth round-trip**

Add to `tests/integration/test_agent_api.py`:

```python
@pytest.mark.asyncio
async def test_register_agent_with_auth(client):
    payload = {
        "agent_id": "auth-agent",
        "name": "Auth Agent",
        "subject": "svc-test",
        "base_url": "http://auth:8080",
        "auth_header": "x-api-key",
        "auth_token": "secret-123",
        "endpoints": [
            {
                "endpoint_type": "chat",
                "method": "POST",
                "path": "/api/chat",
                "mode": "block",
                "idempotent": False,
                "path_params": [],
                "query_params": [],
            }
        ],
    }
    resp = await client.post("/v1/agents", json=payload)
    assert resp.status_code == 201

    # Detail masks token
    resp = await client.get("/v1/agents/auth-agent")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["auth_header"] == "x-api-key"
    assert detail["auth_token"] == "***"

    # List omits token
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["auth_header"] == "x-api-key"
    assert "auth_token" not in items[0]
```

- [ ] **Step 2: Run test**

```bash
python3 -m pytest tests/integration/test_agent_api.py::test_register_agent_with_auth -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_agent_api.py
git commit -m "test: add integration test for agent auth fields"
```

---

### Task 9: Update schema.sql

**Files:**
- Modify: `schema.sql`

- [ ] **Step 1: Add columns to `agents` table**

In `schema.sql`, in the `CREATE TABLE agents` block, after `description TEXT`, add:

```sql
    capability VARCHAR(255),
    description TEXT,
    auth_header VARCHAR(255),
    auth_token VARCHAR(2048)
```

- [ ] **Step 2: Commit**

```bash
git add schema.sql
git commit -m "feat: update schema.sql with auth fields"
```

---

### Task 10: Update Example Agent Config

**Files:**
- Modify: `examples/agents/intelligent-kb-agent.json`

- [ ] **Step 1: Add auth fields**

After the `description` field (or after `base_url` if description is absent), add:

```json
  "auth_header": "x-api-key",
  "auth_token": "your-api-key-here",
```

- [ ] **Step 2: Commit**

```bash
git add examples/agents/intelligent-kb-agent.json
git commit -m "docs: add auth fields to example agent config"
```

---

## Spec Coverage Check

| Requirement | Task |
|-------------|------|
| Store auth_header on Agent | Task 1, 3 |
| Store auth_token on Agent | Task 1, 3 |
| Accept auth fields on registration | Task 2, 7 |
| Inject auth into upstream requests | Task 5 |
| Agent auth overrides downstream header | Task 5 (Step 5) |
| Mask auth_token in detail response | Task 4 |
| Omit auth_token from list response | Task 2, 4 |
| Database migration | Task 6 |
| Tests | Task 4, 5, 7, 8 |
| Example update | Task 10 |

No gaps found.

## Placeholder Scan

No "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling", "handle edge cases", "write tests for the above", or "similar to Task N" found.

## Type Consistency Check

- `auth_header`: `str | None` across model, schema, repo, service, forwarder — consistent.
- `auth_token`: `str | None` across model, schema, repo — consistent. Masked as `"***"` or `None` in responses.
- `Agent.auth_header`, `Agent.auth_token` in Forwarder injection code matches model.

All consistent.
