# Design: Agent Authentication Credentials

## Data Model

```sql
ALTER TABLE agents
    ADD COLUMN auth_header VARCHAR(255),
    ADD COLUMN auth_token VARCHAR(2048);
```

Both nullable. When `auth_header` is set, `auth_token` should also be set.

## Schema Changes

```python
class AgentRegistration(BaseModel):
    ...
    auth_header: str | None = Field(default=None, max_length=255)
    auth_token: str | None = Field(default=None, max_length=2048)

class AgentDetail(BaseModel):
    ...
    auth_header: str | None
    auth_token: str | None  # masked as "***" in response

class AgentListItem(BaseModel):
    ...
    auth_header: str | None
    # auth_token omitted from list view
```

## Forwarder Integration

In `Forwarder.forward()` and `_auto_create_session()`, before calling `client.request()`:

```python
headers = dict(request.headers)
if agent.auth_header and agent.auth_token:
    headers[agent.auth_header] = agent.auth_token
```

The agent's auth header takes precedence over any downstream header with the same name.

## Registry Service

`AgentRegistry.get_agent()` builds the response. When constructing `AgentDetail`:
- Pass through `auth_header`
- Replace `auth_token` with `"***"` (or `None`) before returning

`AgentRegistry.register()` persists raw token as-is.

## Repository

`AgentRepository.create()` stores both fields from `AgentRegistration`.

## API

No new endpoints. Existing endpoints updated:
- `POST /v1/agents` — accepts `auth_header` / `auth_token`
- `GET /v1/agents/{id}` — returns masked token
- `GET /v1/agents` — returns `auth_header` only (no token)

## Files to Change

| File | Change |
|------|--------|
| `agent_routers/models/agent.py` | Add `auth_header`, `auth_token` columns |
| `agent_routers/schemas/agent.py` | Add fields to registration/detail/list schemas |
| `agent_routers/adapters/agent_repo.py` | Persist new fields |
| `agent_routers/services/registry.py` | Mask token in responses |
| `agent_routers/services/forwarder.py` | Inject auth headers into upstream requests |
| `alembic/versions/` | New migration |
| `tests/unit/test_agent_schemas.py` | Test new optional fields |
| `tests/unit/test_forwarder.py` | Test auth header injection |
| `tests/integration/test_agent_api.py` | Test registration + response masking |
| `schema.sql` | Update |
| `examples/agents/intelligent-kb-agent.json` | Add auth fields |
