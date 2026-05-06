# Remove endpoint_id — Design Specification

## Context

The current system uses `endpoint_id` as a per-agent arbitrary string identifier for endpoints (e.g., `"chat"`, `"create-session"`, `"ep-1"`). Routing returns `(agent_id, endpoint_id)`, the forwarder looks up the endpoint config by `endpoint_id`, and the session cache stores `agent_id:endpoint_id`.

Recent changes have already hardcoded `"chat"` as the communication endpoint and `"create-session"` as the internal auto-creation endpoint. The `endpoint_id` abstraction no longer adds value — it is redundant and complicates the data model, routing, caching, and audit pipelines.

## Goal

Remove **all** `endpoint_id` references from the codebase. Replace with a semantic `EndpointType` enum. Each agent still keeps multiple endpoint configs (method, path, param_mapping, etc.), but they are identified by type rather than arbitrary strings.

## Data Model

### EndpointType Enum

```python
class EndpointType(str, Enum):
    CHAT = "chat"
    CREATE_SESSION = "create_session"
    STOP = "stop"
```

### AgentEndpoint

Replace `endpoint_id` with `endpoint_type`:

```python
class AgentEndpoint(Base):
    __tablename__ = "agent_endpoints"

    agent_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True
    )
    endpoint_type: Mapped[EndpointType] = mapped_column(String(16), primary_key=True)
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
```

### RoutingRule

Replace `target_endpoint_id` with `target_endpoint_type` (nullable, for rare cases where a rule wants to force a non-chat endpoint):

```python
class RoutingRule(Base):
    ...
    target_endpoint_type: Mapped[EndpointType | None] = mapped_column(String(16), nullable=True)
```

In practice, rules will usually leave this null, meaning "use the default chat endpoint".

### AuditEvent

Remove `endpoint_id` field entirely. Audit focuses on agent-level routing decisions.

### Session Cache

Format changes from `session:{session_id} = {agent_id}:{endpoint_id}` to `session:{session_id} = {agent_id}`.

The endpoint is always implied: if a session exists, the communication endpoint is `CHAT`.

## Service Layer

### RoutingDecisionEngine

`resolve()` returns `str` (agent_id only) instead of `tuple[str, str]`.

```python
async def resolve(route_req: RouteRequest, headers: dict[str, str]) -> str:
    ...
```

Behavior per level:
- **L1 Preferred**: `X-Preferred-Agent` header selects agent. Endpoint is always `CHAT`.
- **L2 Cache**: Returns cached `agent_id` only.
- **L3 Rules**: Rules select agent only. `target_endpoint_type` is optional; if null, defaults to `CHAT`.
- **L5 Default**: Returns `default_agent_id`.

### Forwarder

- `_find_endpoint(agent, endpoint_type)` replaces `_find_endpoint(agent, endpoint_id)`.
- `forward()` calls `self._find_endpoint(agent, EndpointType.CHAT)`.
- `_auto_create_session()` calls `self._find_endpoint(agent, EndpointType.CREATE_SESSION)`.
- `_forward_stream()` response headers include `X-Preferred-Agent` and `X-Session-Id` — no endpoint reference.

### SessionManager

```python
async def set_route(session_id: str, agent_id: str, ttl: int = DEFAULT_TTL) -> None:
    value = agent_id
    await client.set(f"session:{session_id}", value, ex=ttl)

async def get_route(session_id: str) -> str | None:
    value = await client.get(f"session:{session_id}")
    return value  # directly the agent_id
```

### Signer

Remove `endpoint_id` from the canonical audit signature string:

```python
def canonical(request_id, timestamp_iso, user_subject, agent_id, status_code, latency_ms) -> str:
    return f"{request_id}|{timestamp_iso}|{user_subject}|{agent_id}|{status_code}|{latency_ms}"
```

## Schemas & API

### Agent Registration Schemas

```python
class EndpointSpec(BaseModel):
    endpoint_type: EndpointType  # replaces endpoint_id
    method: str
    path: str
    mode: str  # "block" | "stream"
    param_mapping: dict = Field(default_factory=dict)
    session_config: dict | None = None
```

### Audit API Response

Remove `endpoint_id` from the audit event JSON response.

## DB Migration

1. **agent_endpoints table**:
   - Drop `endpoint_id` column
   - Add `endpoint_type` (String(16), part of composite PK with `agent_id`)

2. **routing_rules table**:
   - Drop `target_endpoint_id` column
   - Add `target_endpoint_type` (String(16), nullable)

3. **audit_events table**:
   - Drop `endpoint_id` column

4. **Redis session cache**:
   - Clear all `session:*` keys (format changed from `agent_id:endpoint_id` to `agent_id`)

## Test Impact

| Test File | Changes |
|-----------|---------|
| `test_forwarder.py` | `endpoint_id="chat"` → `endpoint_type=EndpointType.CHAT`; resolve returns str |
| `test_routing.py` | Remove endpoint assertions; resolve returns str; L1 tests simplified |
| `test_auto_session.py` | create-session uses `EndpointType.CREATE_SESSION` |
| `test_agent_schemas.py` | Schema assertions updated |
| `test_registry_service.py` | Registration payloads updated |
| `test_signer.py` | Signature format updated |

## Rollback Plan

If issues arise post-deployment:
1. Revert code changes via git
2. Run reverse Alembic migration to restore `endpoint_id` columns
3. Re-populate endpoint identifiers from backup or re-register agents

## Files to Modify

| File | Change |
|------|--------|
| `agent_routers/models/agent.py` | Add `EndpointType` enum; update `AgentEndpoint` |
| `agent_routers/models/rule.py` | Replace `target_endpoint_id` with `target_endpoint_type` |
| `agent_routers/models/audit.py` | Remove `endpoint_id` |
| `agent_routers/schemas/agent.py` | Update `EndpointSpec` |
| `agent_routers/services/forwarder.py` | `_find_endpoint` by type; hardcode `CHAT`/`CREATE_SESSION` |
| `agent_routers/services/routing.py` | `resolve()` returns str; remove endpoint from rules/cache |
| `agent_routers/services/session_manager.py` | Simplify to agent_id only |
| `agent_routers/services/registry.py` | Use `endpoint_type` |
| `agent_routers/services/signer.py` | Remove `endpoint_id` from canonical string |
| `agent_routers/services/routing.py` | Update rule resolution |
| `agent_routers/adapters/agent_repo.py` | Use `endpoint_type` |
| `agent_routers/adapters/audit_repo.py` | Remove `endpoint_id` |
| `agent_routers/api/routes_audit.py` | Remove from response |
| `agent_routers/middleware/audit.py` | Remove `endpoint_id` extraction |
| `tests/unit/*` | Update all endpoint references |
| `alembic/versions/` | Add migration |
| `AGENTS.md` | Update architecture docs |
